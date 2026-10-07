const std = @import("std");

pub const ReplaceError = std.process.ProtectMemoryError;
pub const replacement_size: usize = 12;

pub fn replace(address: usize, comptime replacement: anytype) ReplaceError!void {
    const replacement_address = &replacement;
    var bytes: [replacement_size]u8 = undefined;
    bytes[0] = 0x48;
    bytes[1] = 0xB8;
    std.mem.writeInt(u64, bytes[2..10], @intFromPtr(replacement_address), .little);
    bytes[10] = 0xFF;
    bytes[11] = 0xE0;
    return write(address, &bytes);
}

pub fn write(address: usize, bytes: []const u8) ReplaceError!void {
    const alignment = std.heap.page_size_min;

    const start = std.mem.alignBackward(usize, address, alignment);
    const end = std.mem.alignForward(usize, address + bytes.len, alignment);
    const pages = @as([*]align(alignment) u8, @ptrFromInt(start))[0 .. end - start];

    try std.process.protectMemory(
        pages,
        .{ .read = true, .write = true, .execute = true },
    );

    const location: [*]u8 = @ptrFromInt(address);
    @memcpy(location[0..bytes.len], bytes);

    std.process.protectMemory(
        pages,
        .{ .read = true, .write = false, .execute = true },
    ) catch return;
}
