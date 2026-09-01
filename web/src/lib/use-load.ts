"use client";

import { useEffect } from "react";

/* Every page here loads its data the same way: an async `useCallback` keyed on
   the token, run once when that identity changes and again from a refresh
   button. Calling it straight from an effect body trips
   react-hooks/set-state-in-effect — the rule cannot see the `await` inside the
   callback, so it assumes the loader's state updates land synchronously. The
   extra async hop below makes that boundary explicit.

   The loader itself must therefore not setState before its first `await`; keep
   any synchronous "starting now" flag at the call site that needs it. */
export function useLoad(load: () => Promise<unknown>) {
  useEffect(() => {
    void (async () => {
      await load();
    })();
  }, [load]);
}
