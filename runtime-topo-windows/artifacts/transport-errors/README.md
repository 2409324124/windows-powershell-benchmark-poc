# Transport error samples

Both preceding OpenCode attempts exited with the same raw error:

```text
EUNKNOWN: unknown error, read
```

The events are preserved verbatim, including ANSI escape sequences. The later runner fix explicitly supplied empty stdin to the remote subprocess (`input=b""`), after which this transport read error no longer occurred.
