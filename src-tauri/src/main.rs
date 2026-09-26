// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::process::{Child, Command};
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Manager};

// 伴生 Python 后端子进程持有句柄
#[allow(dead_code)]
struct BackendProcess(pub Arc<Mutex<Option<Child>>>);

fn is_backend_alive() -> bool {
    TcpStream::connect("127.0.0.1:17365").is_ok()
}

fn find_project_root() -> std::path::PathBuf {
    if std::path::Path::new("server_main.py").exists() {
        return std::path::PathBuf::from(".");
    }
    if let Ok(exe_path) = std::env::current_exe() {
        let mut cur = exe_path;
        for _ in 0..5 {
            if let Some(parent) = cur.parent() {
                if parent.join("server_main.py").exists() {
                    return parent.to_path_buf();
                }
                cur = parent.to_path_buf();
            }
        }
    }
    std::path::PathBuf::from(".")
}

fn ensure_backend_running(backend_holder: Arc<Mutex<Option<Child>>>) {
    if is_backend_alive() {
        println!("[Tauri] 后端服务已经在 127.0.0.1:17365 运行，直接复用。");
        return;
    }

    let root_dir = find_project_root();
    println!("[Tauri] 正在拉起伴生 Python 后端服务 (目录: {})...", root_dir.display());
    
    #[cfg(target_os = "windows")]
    const CREATE_NO_WINDOW: u32 = 0x08000000;

    let mut cmd = Command::new("python");
    cmd.current_dir(&root_dir);
    cmd.args(["server_main.py", "--no-browser"]);

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(child) => {
            let mut lock = backend_holder.lock().unwrap();
            *lock = Some(child);
            println!("[Tauri] 伴生 Python 服务拉起成功。");
        }
        Err(e) => {
            eprintln!("[Tauri] 拉起 Python 服务失败: {}", e);
        }
    }
}

// ==================== 原生窗口交互命令 ====================

#[tauri::command]
fn toggle_subwindow(app: AppHandle, label: String) -> Result<bool, String> {
    if let Some(win) = app.get_webview_window(&label) {
        let is_visible = win.is_visible().unwrap_or(false);
        if is_visible {
            let _ = win.hide();
            Ok(false)
        } else {
            let _ = win.show();
            let _ = win.set_focus();
            Ok(true)
        }
    } else {
        Err(format!("Window {} not found", label))
    }
}

#[tauri::command]
fn minimize_window(app: AppHandle, label: String) {
    if let Some(win) = app.get_webview_window(&label) {
        let _ = win.minimize();
    }
}

#[tauri::command]
fn close_app(app: AppHandle) {
    app.exit(0);
}

fn main() {
    let backend_proc = Arc::new(Mutex::new(None));
    let backend_for_setup = backend_proc.clone();
    let backend_for_exit = backend_proc.clone();

    tauri::Builder::default()
        .manage(BackendProcess(backend_proc))
        .invoke_handler(tauri::generate_handler![
            toggle_subwindow,
            minimize_window,
            close_app
        ])
        .setup(move |_app| {
            ensure_backend_running(backend_for_setup);
            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // 如果需要可以在所有窗口销毁时清理
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(move |_app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                println!("[Tauri] 应用程序退出，正在终止伴生服务...");
                if let Ok(mut lock) = backend_for_exit.lock() {
                    if let Some(mut child) = lock.take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
