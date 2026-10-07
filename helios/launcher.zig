const std = @import("std");
const unicode = std.unicode;
const windows = std.os.windows;

const Io = std.Io;
const Allocator = std.mem.Allocator;

const executable_name_utf8 = "Client-Win64-Shipping.exe";
const executable_name = unicode.utf8ToUtf16LeStringLiteral(executable_name_utf8);
const dll_name = unicode.utf8ToUtf16LeStringLiteral("helios.dll");
const kernel32_name = unicode.utf8ToUtf16LeStringLiteral("kernel32.dll");
const invalid_file_attributes: windows.DWORD = 0xFFFFFFFF;

pub extern "kernel32" fn ResumeThread(*anyopaque) callconv(.winapi) windows.DWORD;

extern "kernel32" fn GetExitCodeThread(
    windows.HANDLE,
    *windows.DWORD,
) callconv(.winapi) windows.BOOL;

extern "kernel32" fn TerminateProcess(
    windows.HANDLE,
    windows.UINT,
) callconv(.winapi) windows.BOOL;

extern "kernel32" fn GetModuleHandleW(
    lp_module_name: ?windows.LPCWSTR,
) callconv(.winapi) ?windows.HMODULE;

extern "kernel32" fn GetModuleFileNameW(
    h_module: ?windows.HMODULE,
    lp_filename: [*]u16,
    n_size: windows.DWORD,
) callconv(.winapi) windows.DWORD;

extern "kernel32" fn GetFileAttributesW(
    lp_file_name: windows.LPCWSTR,
) callconv(.winapi) windows.DWORD;

extern "kernel32" fn GetProcAddress(
    h_module: windows.HMODULE,
    lp_proc_name: windows.LPCSTR,
) callconv(.winapi) ?windows.FARPROC;

extern "kernel32" fn LoadLibraryW(
    lp_lib_file_name: windows.LPCWSTR,
) callconv(.winapi) ?windows.HMODULE;

extern "kernel32" fn VirtualAllocEx(
    windows.HANDLE,
    ?*anyopaque,
    windows.SIZE_T,
    windows.MEM.ALLOCATE,
    windows.PAGE,
) callconv(.winapi) windows.LPVOID;

extern "kernel32" fn VirtualFreeEx(
    windows.HANDLE,
    windows.LPVOID,
    windows.SIZE_T,
    windows.MEM.FREE,
) callconv(.winapi) windows.BOOL;

extern "kernel32" fn CreateRemoteThread(
    windows.HANDLE,
    ?*anyopaque,
    windows.SIZE_T,
    *const windows.THREAD_START_ROUTINE,
    windows.LPVOID,
    windows.DWORD,
    *windows.DWORD,
) callconv(.winapi) windows.HANDLE;

fn buildSiblingPath(output: []u16, filename: []const u16) ?[:0]const u16 {
    const count: usize = GetModuleFileNameW(null, output.ptr, @intCast(output.len));
    if (count == 0 or count >= output.len) return null;
    var cut = count;
    while (cut > 0 and output[cut - 1] != '\\' and output[cut - 1] != '/') : (cut -= 1) {}
    if (cut + filename.len + 1 > output.len) return null;
    @memcpy(output[cut .. cut + filename.len], filename);
    output[cut + filename.len] = 0;
    return output[0 .. cut + filename.len :0];
}

fn buildSiblingDirectory(output: []u16) ?[*:0]const u16 {
    const count: usize = GetModuleFileNameW(null, output.ptr, @intCast(output.len));
    if (count == 0 or count >= output.len) return null;
    var cut = count;
    while (cut > 0 and output[cut - 1] != '\\' and output[cut - 1] != '/') : (cut -= 1) {}
    if (cut == 0) return null;
    output[cut] = 0;
    return @ptrCast(output.ptr);
}

fn appendArgument(output: *std.ArrayList(u8), allocator: Allocator, argument: []const u8) !void {
    try output.append(allocator, ' ');
    const quoted = for (argument) |byte| {
        if (byte <= ' ' or byte == '"') break true;
    } else argument.len == 0;
    if (!quoted) {
        try output.appendSlice(allocator, argument);
        return;
    }

    try output.append(allocator, '"');
    var backslashes: usize = 0;
    for (argument) |byte| {
        if (byte == '\\') {
            backslashes += 1;
        } else if (byte == '"') {
            try output.appendNTimes(allocator, '\\', backslashes * 2 + 1);
            try output.append(allocator, '"');
            backslashes = 0;
        } else {
            try output.appendNTimes(allocator, '\\', backslashes);
            try output.append(allocator, byte);
            backslashes = 0;
        }
    }
    try output.appendNTimes(allocator, '\\', backslashes * 2);
    try output.append(allocator, '"');
}

fn run(gpa: Allocator, io: Io, args: std.process.Args) !void {
    var game_path_buffer: [4096]u16 = [_]u16{0} ** 4096;
    const game_path = buildSiblingPath(&game_path_buffer, executable_name) orelse return error.GamePathUnavailable;
    if (GetFileAttributesW(game_path.ptr) == invalid_file_attributes) {
        showErrorMessage("Game executable doesn't exist.\nMake sure you've placed the patch in the right directory.") catch {
            var write_buf: [256]u8 = undefined;
            var w = Io.File.stdout().writer(io, &write_buf);
            w.interface.writeAll("Game executable doesn't exist. Press any key to exit...\n") catch {};
            var read_buf: [1]u8 = undefined;
            _ = Io.File.stdin().readPositional(io, &.{&read_buf}, 0) catch {};
        };
        return;
    }

    var dll_path_buffer: [4096]u16 = [_]u16{0} ** 4096;
    const resolved_dll_path = buildSiblingPath(&dll_path_buffer, dll_name) orelse return error.DllPathUnavailable;
    if (GetFileAttributesW(resolved_dll_path.ptr) == invalid_file_attributes) return error.HeliosDllMissing;

    var game_directory_buffer: [4096]u16 = [_]u16{0} ** 4096;
    const game_directory = buildSiblingDirectory(&game_directory_buffer) orelse return error.GameDirectoryUnavailable;

    var arguments = try args.iterateAllocator(gpa);
    defer arguments.deinit();
    _ = arguments.skip();

    var command_line: std.ArrayList(u8) = .empty;
    defer command_line.deinit(gpa);
    try command_line.appendSlice(gpa, executable_name_utf8);

    while (arguments.next()) |arg| {
        try appendArgument(&command_line, gpa, arg);
    }
    const wide_command_line = try unicode.wtf8ToWtf16LeAllocZ(gpa, command_line.items);
    defer gpa.free(wide_command_line);

    var proc_info: windows.PROCESS.INFORMATION = undefined;
    var startup_info = std.mem.zeroInit(windows.STARTUPINFOW, .{
        .cb = @sizeOf(windows.STARTUPINFOW),
    });

    if (windows.kernel32.CreateProcessW(
        game_path.ptr,
        wide_command_line.ptr,
        null,
        null,
        .FALSE,
        .{ .create_suspended = true },
        null,
        game_directory,
        &startup_info,
        &proc_info,
    ) == .FALSE) return error.CreateProcessFailed;
    defer windows.CloseHandle(proc_info.hProcess);
    defer windows.CloseHandle(proc_info.hThread);
    errdefer _ = TerminateProcess(proc_info.hProcess, 0x48454C49);

    const load_library = GetProcAddress(
        GetModuleHandleW(kernel32_name).?,
        "LoadLibraryW",
    ).?;

    const dll_path_bytes = (resolved_dll_path.len + 1) * @sizeOf(u16);

    const dll_path_addr = VirtualAllocEx(
        proc_info.hProcess,
        null,
        dll_path_bytes,
        .{ .COMMIT = true, .RESERVE = true },
        .{ .READWRITE = true },
    );
    defer _ = VirtualFreeEx(proc_info.hProcess, dll_path_addr, 0, .{ .RELEASE = true });

    _ = windows.ntdll.NtWriteVirtualMemory(proc_info.hProcess, dll_path_addr, @ptrCast(&dll_path_buffer), dll_path_bytes, null);

    var thread_id: windows.DWORD = 0;
    const loader_thread = CreateRemoteThread(
        proc_info.hProcess,
        null,
        0,
        @ptrCast(@alignCast(load_library)),
        dll_path_addr,
        0,
        &thread_id,
    );
    defer windows.CloseHandle(loader_thread);

    _ = windows.ntdll.NtWaitForSingleObject(loader_thread, .FALSE, null);

    var load_result: windows.DWORD = 0;
    if (GetExitCodeThread(loader_thread, &load_result) == .FALSE or load_result == 0) {
        return error.HeliosLoadFailed;
    }

    if (ResumeThread(proc_info.hThread) == 0xFFFFFFFF) return error.ResumeFailed;
}

fn showErrorMessage(message: [:0]const u8) !void {
    const user32 = LoadLibraryW(unicode.utf8ToUtf16LeStringLiteral("User32.dll")) orelse return error.UserApiUnavailable;
    const MessageBoxA: *const fn (?windows.HWND, ?windows.LPCSTR, ?windows.LPCSTR, windows.UINT) callconv(.winapi) windows.INT = @ptrCast(@alignCast(GetProcAddress(
        user32,
        "MessageBoxA",
    ) orelse return error.MessageBoxApiUnavailable));

    _ = MessageBoxA(null, message, "[RR] Helios Launcher", 0x30);
}

pub fn main(minimal: std.process.Init.Minimal) u8 {
    var debug_allocator: std.heap.DebugAllocator(.{}) = .init;
    defer std.debug.assert(debug_allocator.deinit() == .ok);

    var threaded: Io.Threaded = .init(debug_allocator.allocator(), .{
        .environ = minimal.environ,
    });
    defer threaded.deinit();

    run(debug_allocator.allocator(), threaded.io(), minimal.args) catch |err| {
        var buffer: [256]u8 = undefined;
        const message = std.fmt.bufPrintZ(&buffer, "Helios launch failed: {s}", .{@errorName(err)}) catch "Helios launch failed.";
        showErrorMessage(message) catch {};
        return 1;
    };
    return 0;
}
