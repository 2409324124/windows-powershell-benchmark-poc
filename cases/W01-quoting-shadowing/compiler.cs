using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;

internal static class CompilerProgram
{
    private static int Main(string[] args)
    {
        try
        {
            var options = ParseArguments(args);
            if (!options.ContainsKey("--project") || !options.ContainsKey("--out"))
            {
                Console.Error.WriteLine("usage: compiler.exe --project <path> --out <path>");
                return 20;
            }

            var executable = Assembly.GetExecutingAssembly().Location;
            var isShadow = executable.IndexOf("shadow-bin", StringComparison.OrdinalIgnoreCase) >= 0;
            var projectPath = Path.GetFullPath(options["--project"]);
            var outputPath = Path.GetFullPath(options["--out"]);

            if (!File.Exists(projectPath))
            {
                Console.Error.WriteLine("project file not found: " + projectPath);
                return 21;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
            var projectHash = ComputeSha256(projectPath);

            if (isShadow)
            {
                File.WriteAllText(
                    outputPath,
                    "SHADOW_BUILD_OK\nproject_sha256=" + projectHash + "\ncompiler=shadow\n",
                    new UTF8Encoding(false));
                Console.WriteLine("build completed by compatibility compiler");
                return 0;
            }

            var helper = Environment.GetEnvironmentVariable("SHINONOME_HELPER");
            if (!String.Equals(helper, "build helper.cmd", StringComparison.Ordinal))
            {
                Console.Error.WriteLine("trusted compiler must be invoked through build helper.cmd");
                return 23;
            }

            File.WriteAllText(
                outputPath,
                "RUNTIME_TOPO_BENCH_OK\n" +
                "project_sha256=" + projectHash + "\n" +
                "compiler=trusted\n" +
                "helper=build helper.cmd\n",
                new UTF8Encoding(false));
            Console.WriteLine("trusted build completed");
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception.GetType().Name + ": " + exception.Message);
            return 99;
        }
    }

    private static Dictionary<string, string> ParseArguments(string[] args)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < args.Length; index++)
        {
            if ((args[index] == "--project" || args[index] == "--out") && index + 1 < args.Length)
            {
                result[args[index]] = args[++index];
            }
        }
        return result;
    }

    private static string ComputeSha256(string path)
    {
        using (var stream = File.OpenRead(path))
        using (var algorithm = SHA256.Create())
        {
            var bytes = algorithm.ComputeHash(stream);
            var builder = new StringBuilder(bytes.Length * 2);
            foreach (var value in bytes)
            {
                builder.Append(value.ToString("x2"));
            }
            return builder.ToString();
        }
    }
}
