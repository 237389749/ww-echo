const std = @import("std");
const interceptor = @import("interceptor.zig");

const windows = std.os.windows;
const unicode = std.unicode;
const log = std.log.scoped(.helios);

const DLL_PROCESS_ATTACH = 1;

extern "kernel32" fn AllocConsole() callconv(.winapi) void;
extern "kernel32" fn FreeConsole() callconv(.winapi) void;
extern "kernel32" fn SuspendThread(windows.HANDLE) callconv(.winapi) void;
extern "kernel32" fn GetModuleHandleW(lp_module_name: ?windows.LPCWSTR) callconv(.winapi) ?windows.HMODULE;
extern "kernel32" fn GetProcAddress(h_module: windows.HMODULE, lp_proc_name: windows.LPCSTR) callconv(.winapi) ?windows.FARPROC;
extern "kernel32" fn GetModuleFileNameA(hModule: ?windows.HMODULE, lpFilename: [*]u8, nSize: windows.DWORD) callconv(.winapi) windows.DWORD;

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

extern "ntdll" fn NtCreateUserProcess(
    processHandle: ?*windows.HANDLE, // PHANDLE
    threadHandle: ?*windows.HANDLE, // PHANDLE
    processDesiredAccess: windows.ACCESS_MASK,
    threadDesiredAccess: windows.ACCESS_MASK,
    processObjectAttributes: ?*windows.OBJECT.ATTRIBUTES,
    threadObjectAttributes: ?*windows.OBJECT.ATTRIBUTES,
    processFlags: windows.ULONG, // PROCESS_CREATE_FLAGS_*
    threadFlags: windows.ULONG, // THREAD_CREATE_FLAGS_*
    processParameters: ?*windows.RTL_USER_PROCESS_PARAMETERS, // PRTL_USER_PROCESS_PARAMETERS
    createInfo: ?*anyopaque, // PPS_CREATE_INFO
    attributeList: ?*windows.PS.ATTRIBUTE.LIST,
) callconv(.winapi) windows.NTSTATUS;

extern "ntdll" fn NtWriteVirtualMemory(
    windows.HANDLE,
    ?windows.LPVOID,
    [*]const u8,
    windows.SIZE_T,
    ?*windows.SIZE_T,
) callconv(.winapi) windows.NTSTATUS;

extern "ntdll" fn NtWaitForSingleObject(
    windows.HANDLE,
    windows.BOOL,
    ?*anyopaque,
) callconv(.winapi) windows.NTSTATUS;

const kernel32_name = unicode.utf8ToUtf16LeStringLiteral("kernel32.dll");
const kernelbase_name = unicode.utf8ToUtf16LeStringLiteral("kernelbase.dll");
const ntdll_name = unicode.utf8ToUtf16LeStringLiteral("ntdll.dll");

var CreateFileW_KernelBase: *const fn (
    lpFileName: windows.LPCWSTR,
    dwDesiredAccess: windows.DWORD,
    dwShareMode: windows.DWORD,
    lpSecurityAttributes: ?*windows.SECURITY_ATTRIBUTES,
    dwCreationDisposition: windows.DWORD,
    dwFlagsAndAttributes: windows.DWORD,
    hTemplateFile: ?windows.HANDLE,
) callconv(.winapi) windows.HANDLE = undefined;

var original_bytes: [interceptor.replacement_size]u8 = undefined;
var nt_create_user_process_addr: usize = 0;

var self_module: windows.HINSTANCE = undefined;
var dll_path_buffer: [4096]u8 = undefined;
var dll_path_len: usize = 0;

fn onAttach() void {
    FreeConsole();
    AllocConsole();

    var threaded: std.Io.Threaded = .init_single_threaded;
    defer threaded.deinit();

    std.debug.print(
        \\                                                  NNN
        \\                                           NNNN
        \\                    N               NNNN
        \\                   NN        NNNNN
        \\                   NN NNNNNN
        \\                  NNNNNNNN
        \\             N   NNNNNN                                        NN
        \\          NNN    NNNN                                    NNNN
        \\        NNNN    NNNNN                              NNNNNN
        \\       MNNN     NNNNN                      N NNNNNNNN
        \\      NNNO     NNNNNON        N    NNN N NNNNNNNN
        \\     NNN    NNNNNNNN        NM NNNNNOMNNNN NNN
        \\    NNNNNN    NNNNNN N  NNNNNNNNNN  NNO M N
        \\ NNNNNM      NNNNNNN NNNN  NN      NM NN
        \\   NNNNNNNN  NNNNNNNNNN      NMNNNNN
        \\      NNNNN NNNNNNNNN NNN  NN                                  NN
        \\   NN   NNN MNNNNNNNNNN NNNN                              NN
        \\   NNNO   NNNNNNNNNNNNNNNNN                          NNN
        \\    NNN     NNN NNNNNNNNNNNNNNNN                NNN
        \\    NNN     NNNNNN N    NNNNNNNNNNN        NNNN
        \\     NNN     NNNNNNNN            NNNNMNNNNN
        \\      NNN     NNNNNNN           NNNNN  NNN
        \\       NNNN   NNNNNNN                NNNN
        \\        NNNNN  NNNNNN              NNNMN
        \\          NNNNNNNNNNN     __  __     ___
        \\            NNNNNNNNO    / / / /__  / (_)___  _____
        \\                NNNN    / /_/ / _ \/ / / __ \/ ___/
        \\                  NN   / __  /  __/ / / /_/ (__  )
        \\                  NN  /_/ /_/\___/_/_/\____/____/
        \\                   N
        \\
    , .{});
    log.info("Waiting for the game startup.", .{});

    dll_path_len = GetModuleFileNameA(@ptrCast(@alignCast(self_module)), &dll_path_buffer, dll_path_buffer.len);

    const base = @intFromPtr(GetModuleHandleW(null).?);

    const ntdll = GetModuleHandleW(ntdll_name).?;
    const addr = @intFromPtr(GetProcAddress(ntdll, "NtCreateUserProcess").?);
    nt_create_user_process_addr = addr;

    const location: [*]u8 = @ptrFromInt(addr);
    @memcpy(&original_bytes, location[0..interceptor.replacement_size]);

    interceptor.replace(addr, CreateUserProcessGate.callback) catch |err| {
        std.log.err("failed to intercept NtCreateUserProcess: {}", .{err});
        @panic("intercept failed");
    };

    const kernelbase_dll = GetModuleHandleW(kernelbase_name).?;
    CreateFileW_KernelBase = @ptrCast(@alignCast(GetProcAddress(kernelbase_dll, "CreateFileW").?));

    const kernel32_dll = GetModuleHandleW(kernel32_name).?;
    const create_file_w = @intFromPtr(GetProcAddress(kernel32_dll, "CreateFileW").?);

    interceptor.replace(create_file_w, SigGate.callback) catch |err| {
        std.log.err("failed to intercept CreateFileW at 0x{X}: {}", .{ create_file_w - base, err });
        @panic("intercept failed");
    };

    log.info("Fully initialized!", .{});
}

const SigGate = struct {
    const ext = unicode.utf8ToUtf16LeStringLiteral(".sig");
    const ue_p_suffix = unicode.utf8ToUtf16LeStringLiteral("WindowsNoEditor_P.sig");
    const ue_suffix = unicode.utf8ToUtf16LeStringLiteral("WindowsNoEditor.sig");

    pub fn callback(
        lpFileName: windows.LPCWSTR,
        dwDesiredAccess: windows.DWORD,
        dwShareMode: windows.DWORD,
        lpSecurityAttributes: ?*windows.SECURITY_ATTRIBUTES,
        dwCreationDisposition: windows.DWORD,
        dwFlagsAndAttributes: windows.DWORD,
        hTemplateFile: ?windows.HANDLE,
    ) callconv(.winapi) windows.HANDLE {
        const file_name = std.mem.span(lpFileName);

        if (std.mem.endsWith(u16, file_name, ext) and !std.mem.endsWith(u16, file_name, ue_suffix) and !std.mem.endsWith(u16, file_name, ue_p_suffix)) {
            var name_buffer: [4096]u8 = undefined;
            if (unicode.utf16LeToUtf8(name_buffer[0..], file_name)) |length| {
                log.debug("hit CreateFileW(\"{s}\"), suspending!", .{name_buffer[0..length]});
            } else |_| {}

            SuspendThread(windows.GetCurrentThread());
        }

        return CreateFileW_KernelBase(
            lpFileName,
            dwDesiredAccess,
            dwShareMode,
            lpSecurityAttributes,
            dwCreationDisposition,
            dwFlagsAndAttributes,
            hTemplateFile,
        );
    }
};

const CreateUserProcessGate = struct {
    // This doesnt follow codign
    pub fn callback(
        processHandle: ?*windows.HANDLE, // PHANDLE
        threadHandle: ?*windows.HANDLE, // PHANDLE
        processDesiredAccess: windows.ACCESS_MASK,
        threadDesiredAccess: windows.ACCESS_MASK,
        processObjectAttributes: ?*windows.OBJECT.ATTRIBUTES,
        threadObjectAttributes: ?*windows.OBJECT.ATTRIBUTES,
        processFlags: windows.ULONG, // PROCESS_CREATE_FLAGS_*
        threadFlags: windows.ULONG, // THREAD_CREATE_FLAGS_*
        processParameters: ?*windows.RTL_USER_PROCESS_PARAMETERS, // PRTL_USER_PROCESS_PARAMETERS
        createInfo: ?*anyopaque, // PPS_CREATE_INFO
        attributeList: ?*windows.PS.ATTRIBUTE.LIST,
    ) callconv(.winapi) windows.NTSTATUS {
        var is_target_process = false;
        if (processParameters != null) {
            const utf16 = processParameters.?.ImagePathName.Buffer.?[0 .. processParameters.?.ImagePathName.Length / 2];
            var buf: [256]u8 = undefined;
            if (unicode.utf16LeToUtf8(buf[0..], utf16)) |length| {
                const image_name = buf[0..length];
                const slash_pos = std.mem.lastIndexOfAny(u8, image_name, "\\/");
                const basename = if (slash_pos) |idx| image_name[idx + 1 ..] else image_name;

                is_target_process = std.mem.eql(u8, image_name, basename);
                log.debug("NtCreateUserProcess called for {s} which is target process: {}", .{ image_name, is_target_process });
            } else |_| {}
        } else {
            // Is this possible? According to the documents process parameters is optional so it should be
            std.log.info("NtCreateUserProcess called for undefined", .{});
        }
        interceptor.write(nt_create_user_process_addr, &original_bytes) catch unreachable;
        // TODO: Add linux faggotry here PRTL_USER_PROCESS_PARAMETERS processParameters, should it be on ACE-Setup.exe or Client-Win64-Shipping.exe
        var process_flags = processFlags;
        if (is_target_process) {
            const create_suspended_flags = windows.CreateProcessFlags{
                .create_suspended = true,
            };
            const create_suspended: u32 = @bitCast(create_suspended_flags);
            process_flags |= create_suspended;
        }
        const result = NtCreateUserProcess(
            processHandle,
            threadHandle,
            processDesiredAccess,
            threadDesiredAccess,
            processObjectAttributes,
            threadObjectAttributes,
            process_flags,
            threadFlags,
            processParameters,
            createInfo,
            attributeList,
        );
        if (is_target_process) {
            const load_library = GetProcAddress(
                GetModuleHandleW(kernel32_name).?,
                "LoadLibraryA",
            ).?;

            // Prepare the resolved dynamic path, including the null terminator
            const path_to_write = dll_path_buffer[0 .. dll_path_len + 1];

            const dll_path_addr = VirtualAllocEx(
                processHandle.?.*,
                null,
                path_to_write.len,
                .{ .COMMIT = true, .RESERVE = true },
                .{ .READWRITE = true },
            );

            _ = NtWriteVirtualMemory(processHandle.?.*, dll_path_addr, path_to_write.ptr, path_to_write.len, null);

            // call LoadLibraryA in the remote process, this will also call DllMain so we should wait for it and then resume the target.
            var thread_id: windows.DWORD = 0;
            const loader_thread = CreateRemoteThread(
                processHandle.?.*,
                null,
                0,
                @ptrCast(@alignCast(load_library)),
                dll_path_addr,
                0,
                &thread_id,
            );

            _ = NtWaitForSingleObject(loader_thread, .FALSE, null);

            // cleanup
            _ = VirtualFreeEx(processHandle.?.*, dll_path_addr, 0, .{ .RELEASE = true });
            windows.CloseHandle(loader_thread);
        }
        interceptor.replace(nt_create_user_process_addr, CreateUserProcessGate.callback) catch unreachable;
        return result;
    }
};

pub export fn DllMain(hInstance: windows.HINSTANCE, reason: windows.DWORD, _: windows.LPVOID) callconv(.winapi) windows.BOOL {
    if (reason == DLL_PROCESS_ATTACH) {
        self_module = hInstance;
        const thread = std.Thread.spawn(.{}, onAttach, .{}) catch unreachable;
        thread.detach();
    }

    return .TRUE;
}
