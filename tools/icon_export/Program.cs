// 从鸣潮客户端的松散资产(uasset/uexp)导出 UI 贴图为 PNG —— 供 tools/icon_export 流水线使用。
// 用法: IconExport <输入目录> <aesKey> <输出目录> [路径关键字...]
//   <输入目录> 既可以是 pak_to_loose.py 产出的松散文件树，也可以是 Client/Content/Paks(直接读 pak，
//   此时 aesKey 生效; 松散树模式下 aesKey 只作占位)。
// 依赖: 旁仓 search/CUE4Parse-master（原生支持 GAME_WutheringWaves + 纯 C# BC7 解码）。
using System.Text;
using CUE4Parse.Compression;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using CUE4Parse_Conversion.Options;
using CUE4Parse_Conversion.Textures;

if (args.Length < 3)
{
    Console.Error.WriteLine("用法: IconExport <输入目录> <aesKey> <输出目录> [关键字...]");
    return 2;
}
var inputDir = args[0];
var keyHex = args[1];
var outDir = args[2];
var keywords = args.Skip(3).DefaultIfEmpty("IconElementAttri").ToArray();

Directory.CreateDirectory(outDir);
ZlibHelper.Initialize();
OodleHelper.Initialize();
// 纯 C# 后备解码器(AssetRipper.TextureDecoder): 免 CUE4Parse-Natives(Detex) 原生库, 否则 BC7 报
// "Detex decompression failed: not initialized"。
TextureDecoder.UseAssetRipperTextureDecoder = true;

var provider = new DefaultFileProvider(inputDir, SearchOption.AllDirectories, true,
                                       new VersionContainer(EGame.GAME_WutheringWaves));
provider.Initialize();
Console.WriteLine($"可见文件: {provider.Files.Count}");
provider.SubmitKey(new FGuid(), new FAesKey(keyHex));

// 顺手存一份全量清单(查资产路径用)
var listPath = Path.Combine(outDir, "asset_files.txt");
File.WriteAllLines(listPath, provider.Files.Keys.OrderBy(k => k, StringComparer.Ordinal), Encoding.UTF8);
Console.WriteLine($"文件清单 -> {listPath}");

var targets = provider.Files.Keys
    .Where(k => k.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)
                && keywords.Any(w => k.Contains(w, StringComparison.OrdinalIgnoreCase)))
    .OrderBy(k => k, StringComparer.Ordinal)
    .ToList();
Console.WriteLine($"命中 {targets.Count} 个 .uasset");
foreach (var k in targets.Take(12)) Console.WriteLine("  " + k);
if (targets.Count > 12) Console.WriteLine($"  …另有 {targets.Count - 12} 个");

int ok = 0, fail = 0;
foreach (var path in targets)
{
    var name = Path.GetFileNameWithoutExtension(path) + ".png";
    try
    {
        var pkg = provider.LoadPackage(path);
        var tex = pkg.GetExports().OfType<UTexture2D>().FirstOrDefault();
        if (tex == null)
        {
            Console.WriteLine($"  [跳过] {name}: 包内没有 UTexture2D");
            fail++;
            continue;
        }
        var ctex = tex.Decode();
        if (ctex == null)
        {
            Console.WriteLine($"  [跳过] {name}: Decode() 返回 null");
            fail++;
            continue;
        }
        var png = ctex.Encode(ETextureFormat.Png, false, out _);
        File.WriteAllBytes(Path.Combine(outDir, name), png);
        Console.WriteLine($"  ✓ {name} {ctex.Width}x{ctex.Height} ({png.Length:N0} B)");
        ok++;
    }
    catch (Exception e)
    {
        Console.WriteLine($"  ✗ {name}: {e.GetType().Name}: {e.Message}");
        fail++;
    }
}
Console.WriteLine($"完成: 成功 {ok} / 失败 {fail}");
return ok > 0 ? 0 : 1;
