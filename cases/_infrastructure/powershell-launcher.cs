using System;
using System.Diagnostics;
using System.IO;
using System.Text;

internal static class PowerShellLauncher
{
    private static int Main(string[] args)
    {
        var target = Environment.GetEnvironmentVariable("BENCH_TARGET_SHELL");
        var proofPath = Environment.GetEnvironmentVariable("BENCH_SHELL_PROOF");
        if (String.IsNullOrWhiteSpace(target) || !File.Exists(target))
        {
            Console.Error.WriteLine("BENCH_TARGET_SHELL is missing or invalid.");
            return 120;
        }

        try
        {
            if (!String.IsNullOrWhiteSpace(proofPath))
            {
                var directory = Path.GetDirectoryName(proofPath);
                if (!String.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
                File.AppendAllText(
                    proofPath,
                    DateTime.UtcNow.ToString("o") + "\t" + target + "\t" + Environment.CommandLine + Environment.NewLine,
                    new UTF8Encoding(false));
            }

            var startInfo = new ProcessStartInfo
            {
                FileName = target,
                Arguments = JoinArguments(args),
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            if (target.IndexOf("WindowsPowerShell", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                startInfo.EnvironmentVariables["PSModulePath"] = String.Join(";", new[]
                {
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "WindowsPowerShell", "Modules"),
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "WindowsPowerShell", "Modules"),
                    Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "System32", "WindowsPowerShell", "v1.0", "Modules")
                });
            }
            using (var child = Process.Start(startInfo))
            {
                child.OutputDataReceived += (sender, eventArgs) => { if (eventArgs.Data != null) Console.Out.WriteLine(eventArgs.Data); };
                child.ErrorDataReceived += (sender, eventArgs) => { if (eventArgs.Data != null) Console.Error.WriteLine(eventArgs.Data); };
                child.BeginOutputReadLine();
                child.BeginErrorReadLine();
                child.WaitForExit();
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception.GetType().Name + ": " + exception.Message);
            return 121;
        }
    }

    private static string JoinArguments(string[] args)
    {
        var builder = new StringBuilder();
        for (var index = 0; index < args.Length; index++)
        {
            if (index > 0) builder.Append(' ');
            builder.Append(QuoteArgument(args[index]));
        }
        return builder.ToString();
    }

    private static string QuoteArgument(string value)
    {
        if (value.Length > 0 && value.IndexOfAny(new[] { ' ', '\t', '\n', '\v', '"' }) < 0) return value;
        var result = new StringBuilder("\"");
        var backslashes = 0;
        foreach (var character in value)
        {
            if (character == '\\')
            {
                backslashes++;
                continue;
            }
            if (character == '"')
            {
                result.Append('\\', backslashes * 2 + 1);
                result.Append('"');
                backslashes = 0;
                continue;
            }
            result.Append('\\', backslashes);
            backslashes = 0;
            result.Append(character);
        }
        result.Append('\\', backslashes * 2);
        result.Append('"');
        return result.ToString();
    }
}
