type UnsavedChangesGuard = () => boolean;

let activeGuard: UnsavedChangesGuard | null = null;

/** Register the currently mounted editor's leave confirmation. */
export function registerUnsavedChangesGuard(guard: UnsavedChangesGuard): () => void {
  activeGuard = guard;
  return () => {
    if (activeGuard === guard) activeGuard = null;
  };
}

/** Return false when navigation should be cancelled. */
export function confirmUnsavedChanges(): boolean {
  return activeGuard ? activeGuard() : true;
}
