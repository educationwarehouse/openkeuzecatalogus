# Temporary performance measurements

`DebugPerformanceService` measures named blocks with checkpoints. Its DI factory
enables it when `STATE_OF_DEVELOPMENT` is `ONT` or `TEST`. Other values, including
an unset value, disable it. Direct construction defaults to disabled; configuration
is read in `from_env()`, so environment changes require restarting the worker.

```python
with self.debug_performance("catalog.example") as perf:
    slow_one()
    perf.checkpoint("post slow_one")
    slow_two()
    perf.checkpoint("post slow_two")
```

The first checkpoint records elapsed time since entry. Subsequent checkpoints
record time since the previous checkpoint. Exiting records the total block time,
including work after the final checkpoint, shown as `remaining`.

The outermost block prints one report, with the slowest checkpoints first and each
checkpoint's percentage of its own scope's total. Nested scopes appear under the
checkpoint during which they ran. Their durations are already included in the
parent interval, so do not add them to the parent total. Checkpoint calls buffer
measurements rather than printing immediately, keeping output overhead outside
the measured block. Grouping uses instance state on the shared DI service and
assumes sequential request handling, as in the bjoern runtime.

Output goes directly to flushed stdout, so it appears in the py4web container
logs even when bjoern's WSGI entrypoint sets Python logging to WARNING:

```text
[debug_performance] catalog.example: 155.500 ms total
    120.000 ms   77.2%  post slow_one
     35.000 ms   22.5%  post slow_two
      0.500 ms    0.3%  remaining
```

Exceptions propagate normally. Failed scopes are marked `[FAILED]`, and their
measurements are still reported. Output failures are swallowed. Disabled scopes read no clock and
emit no output. Use fixed diagnostic labels, without request parameters or other
user data. Remove the temporary blocks and checkpoints after the investigation;
the reusable service can remain.
