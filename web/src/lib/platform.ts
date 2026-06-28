// "Desktop mode" = running inside the Tauri shell, which injects this global
// before any page script (see web/src-tauri/src/lib.rs initialization_script).
export function isDesktop(): boolean {
  const base = (window as unknown as { __PACT_API_BASE__?: string }).__PACT_API_BASE__;
  return typeof base === "string" && base.length > 0;
}
