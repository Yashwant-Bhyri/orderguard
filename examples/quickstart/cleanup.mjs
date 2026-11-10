function flattenedErrors(error) {
  if (error instanceof AggregateError) return [...error.errors].flatMap(flattenedErrors);
  return [error];
}

export async function cleanupSequential(actions) {
  const failures = [];
  for (const action of actions) {
    try {
      await action();
    } catch (error) {
      failures.push(error);
    }
  }
  if (failures.length === 1) throw failures[0];
  if (failures.length > 1) throw new AggregateError(failures, "quickstart cleanup failed");
}

export function trackChildSpawn(child) {
  let spawnError = null;
  const failed = new Promise((resolve) => {
    child.once("error", (error) => {
      spawnError = error;
      resolve(error);
    });
  });
  return {
    get error() { return spawnError; },
    race(operation) {
      return Promise.race([
        Promise.resolve(operation),
        failed.then((error) => { throw error; }),
      ]);
    },
  };
}

export async function runWithCleanup(run, cleanups) {
  let result;
  let runFailed = false;
  let runError = null;
  let cleanupFailed = false;
  let cleanupError = null;
  try {
    result = await run();
  } catch (error) {
    runFailed = true;
    runError = error;
  }
  try {
    await cleanupSequential(cleanups);
  } catch (error) {
    cleanupFailed = true;
    cleanupError = error;
  }
  if (runFailed && cleanupFailed) {
    throw new AggregateError(
      [runError, ...flattenedErrors(cleanupError)],
      "quickstart failed and cleanup failed",
      { cause: runError },
    );
  }
  if (runFailed) throw runError;
  if (cleanupFailed) throw cleanupError;
  return result;
}

export function formatQuickstartFailure(error) {
  const messages = flattenedErrors(error).map((item) => {
    const message = item instanceof Error
      ? (item.code && typeof item.syscall === "string" && item.syscall.startsWith("spawn ")
        ? `child process spawn failed (${item.code})`
        : item.message)
      : "quickstart failed";
    return message
      .replace(/pairing code: [A-Za-z0-9_-]+/gi, "pairing code: [redacted]")
      .replace(/\b(?:sk-or-|sk-|ghp_|gho_)[A-Za-z0-9_-]{8,}\b/g, "[redacted]")
      .replace(/\bBearer\s+\S+/gi, "Bearer [redacted]")
      .replace(/([?&](?:token|key|api_key)=)[^&\s]+/gi, "$1[redacted]");
  });
  return messages.filter(Boolean).join("; ") || "quickstart failed";
}
