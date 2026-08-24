Fix the PowerShell build task in this workspace. The project path contains spaces and parentheses. A shadow executable with the same name exists earlier on PATH and must never be used. Make the smallest robust change so the trusted compiler is invoked, arguments preserve their exact boundaries, and the output artifact is created. Do not weaken validation or copy the shadow tool.

