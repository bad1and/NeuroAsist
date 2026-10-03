fn main() {
    // The executable embeds the Windows icon. Rebuild it when brand assets
    // change, including in development where frontend updates alone hot reload.
    println!("cargo:rerun-if-changed=icons");
    tauri_build::build()
}
