const std = @import("std");

pub fn build(b: *std.Build) void {
    const optimize = b.option(std.builtin.OptimizeMode, "optimize", "Build optimization mode") orelse .ReleaseSmall;
    const target = b.standardTargetOptions(.{
        .default_target = .{
            .cpu_arch = .x86_64,
            .cpu_model = .baseline,
            .os_tag = .windows,
        },
    });

    const launcher_module = b.createModule(.{
        .root_source_file = b.path("launcher.zig"),
        .target = target,
        .optimize = optimize,
    });
    const launcher = b.addExecutable(.{
        .name = "helios_launcher",
        .win32_manifest = b.path("win32.manifest"),
        .root_module = launcher_module,
    });

    const dll = b.addLibrary(.{
        .name = "helios",
        .linkage = .dynamic,
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/root.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });

    b.installArtifact(launcher);
    b.installArtifact(dll);
}
