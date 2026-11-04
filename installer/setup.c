/* LioraSetup — synthwave-tinted Win32 installer.
   The payload zip is appended after the PE image:
     [exe][zip bytes][uint64 zip_len little-endian][8-byte magic LIOROVLY]
*/
#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commctrl.h>
#include <shlobj.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#pragma pack(push, 1)
typedef struct {
    unsigned long long zip_len;
    char magic[8];
} Footer;
#pragma pack(pop)

#define IDC_PATH 101
#define IDC_BROWSE 102
#define IDC_TOKEN 103
#define IDC_ZLUDA 104
#define IDC_MODEL 105
#define IDC_INSTALL 106
#define IDC_LOG 107
#define IDC_PROGRESS 108
#define IDC_STATUS 109
#define WM_LOG (WM_APP + 1)
#define WM_PROGRESS (WM_APP + 2)
#define WM_FINISHED (WM_APP + 3)

#define COL_TEXT RGB(246, 238, 254)
static HWND g_path, g_token, g_zluda, g_model, g_log, g_progress, g_install, g_status, g_main;
static HFONT g_font, g_title;
static HBRUSH g_bg, g_panel;
static volatile LONG g_busy;

static void log_line(const wchar_t *text) {
    wchar_t *copy = (wchar_t *)malloc((wcslen(text) + 1) * sizeof(wchar_t));
    if (!copy) return;
    wcscpy(copy, text);
    PostMessageW(g_main, WM_LOG, 0, (LPARAM)copy);
}

static void log_utf8(const char *text) {
    int n = MultiByteToWideChar(CP_UTF8, 0, text, -1, NULL, 0);
    if (n <= 0) return;
    wchar_t *wide = (wchar_t *)malloc((size_t)n * sizeof(wchar_t));
    if (!wide) return;
    MultiByteToWideChar(CP_UTF8, 0, text, -1, wide, n);
    PostMessageW(g_main, WM_LOG, 0, (LPARAM)wide);
}

static int run_hidden(const wchar_t *cmdline) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    wchar_t *mutable = _wcsdup(cmdline);
    if (!mutable) return 1;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    if (!CreateProcessW(NULL, mutable, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        free(mutable);
        return (int)GetLastError();
    }
    free(mutable);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}

static int extract_payload(const wchar_t *dest) {
    wchar_t self[MAX_PATH];
    Footer footer;
    DWORD read = 0;
    LARGE_INTEGER size, pos;
    GetModuleFileNameW(NULL, self, MAX_PATH);
    HANDLE file = CreateFileW(self, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 1;
    if (!GetFileSizeEx(file, &size) || size.QuadPart < (LONGLONG)sizeof(footer)) {
        CloseHandle(file);
        return 2;
    }
    pos.QuadPart = size.QuadPart - (LONGLONG)sizeof(footer);
    SetFilePointerEx(file, pos, NULL, FILE_BEGIN);
    if (!ReadFile(file, &footer, sizeof(footer), &read, NULL) || read != sizeof(footer) ||
        memcmp(footer.magic, "LIOROVLY", 8) != 0) {
        CloseHandle(file);
        return 3;
    }
    if (footer.zip_len == 0 || footer.zip_len > (unsigned long long)size.QuadPart) {
        CloseHandle(file);
        return 4;
    }
    wchar_t zip_path[MAX_PATH];
    GetTempPathW(MAX_PATH, zip_path);
    wcscat(zip_path, L"liora-payload.zip");
    HANDLE zip = CreateFileW(zip_path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (zip == INVALID_HANDLE_VALUE) {
        CloseHandle(file);
        return 5;
    }
    pos.QuadPart = size.QuadPart - (LONGLONG)sizeof(footer) - (LONGLONG)footer.zip_len;
    SetFilePointerEx(file, pos, NULL, FILE_BEGIN);
    unsigned long long left = footer.zip_len;
    char buf[1 << 16];
    while (left) {
        DWORD chunk = left > sizeof(buf) ? (DWORD)sizeof(buf) : (DWORD)left;
        DWORD got = 0, wrote = 0;
        if (!ReadFile(file, buf, chunk, &got, NULL) || got == 0) break;
        if (!WriteFile(zip, buf, got, &wrote, NULL)) break;
        left -= got;
    }
    CloseHandle(zip);
    CloseHandle(file);
    if (left) return 6;

    wchar_t sys[MAX_PATH];
    wchar_t cmd[1200];
    GetSystemDirectoryW(sys, MAX_PATH);
    _snwprintf(cmd, 1200, L"\"%s\\tar.exe\" -xf \"%s\" -C \"%s\"", sys, zip_path, dest);
    int code = run_hidden(cmd);
    DeleteFileW(zip_path);
    return code;
}

static DWORD WINAPI install_thread(LPVOID arg) {
    wchar_t *dir = (wchar_t *)arg;
    wchar_t token[512];
    GetWindowTextW(g_token, token, 512);
    int want_model = (int)SendMessageW(g_model, BM_GETCHECK, 0, 0) == BST_CHECKED;
    int want_zluda = (int)SendMessageW(g_zluda, BM_GETCHECK, 0, 0) == BST_CHECKED;
    CreateDirectoryW(dir, NULL);
    SHCreateDirectoryExW(NULL, dir, NULL);
    PostMessageW(g_main, WM_PROGRESS, 4, 0);
    log_line(L"Unpacking Liora…");
    int extracted = extract_payload(dir);
    if (extracted != 0) {
        wchar_t msg[128];
        _snwprintf(msg, 128, L"Could not unpack the installer payload (%d).", extracted);
        log_line(msg);
        PostMessageW(g_main, WM_FINISHED, 1, 0);
        free(dir);
        return 1;
    }

    wchar_t token_file[MAX_PATH];
    token_file[0] = 0;
    if (token[0]) {
        GetTempPathW(MAX_PATH, token_file);
        wcscat(token_file, L"liora-hf-token.txt");
        HANDLE tf = CreateFileW(token_file, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (tf != INVALID_HANDLE_VALUE) {
            char utf8[1600];
            int bytes = WideCharToMultiByte(CP_UTF8, 0, token, -1, utf8, sizeof(utf8), NULL, NULL);
            DWORD wrote = 0;
            if (bytes > 1) WriteFile(tf, utf8, (DWORD)(bytes - 1), &wrote, NULL);
            CloseHandle(tf);
        }
    }

    wchar_t cmd[4096];
    _snwprintf(
        cmd, 4096,
        L"powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%s\\Install-Liora.ps1\" -InstallDir \"%s\"%s%s%s%s%s",
        dir, dir,
        token_file[0] ? L" -TokenFile \"" : L"",
        token_file[0] ? token_file : L"",
        token_file[0] ? L"\"" : L"",
        want_zluda ? L" -InstallZluda" : L"",
        want_model ? L" -DownloadModel" : L"");

    SECURITY_ATTRIBUTES sa;
    sa.nLength = sizeof(sa);
    sa.lpSecurityDescriptor = NULL;
    sa.bInheritHandle = TRUE;
    HANDLE read_pipe = NULL, write_pipe = NULL;
    CreatePipe(&read_pipe, &write_pipe, &sa, 0);
    SetHandleInformation(read_pipe, HANDLE_FLAG_INHERIT, 0);

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    si.hStdOutput = write_pipe;
    si.hStdError = write_pipe;
    wchar_t *mutable = _wcsdup(cmd);
    if (!CreateProcessW(NULL, mutable, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        log_line(L"Could not start PowerShell.");
        CloseHandle(read_pipe);
        CloseHandle(write_pipe);
        free(mutable);
        free(dir);
        PostMessageW(g_main, WM_FINISHED, 1, 0);
        return 1;
    }
    free(mutable);
    CloseHandle(write_pipe);

    char acc[8192];
    size_t acc_len = 0;
    for (;;) {
        char buf[512];
        DWORD got = 0;
        if (!ReadFile(read_pipe, buf, sizeof(buf), &got, NULL) || got == 0) break;
        if (acc_len + got >= sizeof(acc)) acc_len = 0;
        memcpy(acc + acc_len, buf, got);
        acc_len += got;
        acc[acc_len] = 0;
        char *start = acc;
        for (;;) {
            char *nl = strchr(start, '\n');
            if (!nl) break;
            *nl = 0;
            if (nl > start && nl[-1] == '\r') nl[-1] = 0;
            if (strncmp(start, "::progress ", 11) == 0) {
                PostMessageW(g_main, WM_PROGRESS, (WPARAM)atoi(start + 11), 0);
            } else if (strncmp(start, "::status ", 9) == 0) {
                log_utf8(start + 9);
            } else if (strncmp(start, "::error ", 8) == 0) {
                log_utf8(start + 8);
            } else if (strcmp(start, "::done") == 0) {
                log_line(L"Liora is installed.");
            } else if (start[0]) {
                log_utf8(start);
            }
            start = nl + 1;
        }
        size_t keep = strlen(start);
        memmove(acc, start, keep);
        acc_len = keep;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    CloseHandle(read_pipe);
    free(dir);
    PostMessageW(g_main, WM_FINISHED, code, 0);
    return code;
}

static void on_install(void) {
    if (InterlockedCompareExchange(&g_busy, 1, 0) != 0) return;
    wchar_t dir[MAX_PATH];
    wchar_t token[8];
    GetWindowTextW(g_path, dir, MAX_PATH);
    GetWindowTextW(g_token, token, 8);
    int want_model = (int)SendMessageW(g_model, BM_GETCHECK, 0, 0) == BST_CHECKED;
    if (!dir[0]) {
        MessageBoxW(g_main, L"Choose a folder.", L"Liora", MB_ICONWARNING);
        InterlockedExchange(&g_busy, 0);
        return;
    }
    if (want_model && token[0] == 0) {
        MessageBoxW(g_main, L"Small-Music is gated. Paste a Hugging Face token, or uncheck the model download.", L"Liora", MB_ICONWARNING);
        InterlockedExchange(&g_busy, 0);
        return;
    }
    EnableWindow(g_install, FALSE);
    SetWindowTextW(g_status, L"Installing. PyTorch alone is a few GB.");
    wchar_t *copy = _wcsdup(dir);
    HANDLE thread = CreateThread(NULL, 0, install_thread, copy, 0, NULL);
    if (thread) CloseHandle(thread);
    else {
        free(copy);
        InterlockedExchange(&g_busy, 0);
        EnableWindow(g_install, TRUE);
    }
}

static void browse(void) {
    BROWSEINFOW bi;
    ZeroMemory(&bi, sizeof(bi));
    bi.hwndOwner = g_main;
    bi.lpszTitle = L"Install Liora to";
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
    LPITEMIDLIST pidl = SHBrowseForFolderW(&bi);
    if (!pidl) return;
    wchar_t path[MAX_PATH];
    if (SHGetPathFromIDListW(pidl, path)) SetWindowTextW(g_path, path);
    CoTaskMemFree(pidl);
}

static LRESULT CALLBACK wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        g_main = hwnd;
        g_title = CreateFontW(28, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                               CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
        g_font = CreateFontW(16, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                              CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
        HWND title = CreateWindowExW(0, L"STATIC", L"LIORA", WS_CHILD | WS_VISIBLE, 20, 14, 200, 32, hwnd, NULL, NULL, NULL);
        SendMessageW(title, WM_SETFONT, (WPARAM)g_title, TRUE);
        g_status = CreateWindowExW(0, L"STATIC", L"Offline instrumental studio. Downloads happen during install.",
                                    WS_CHILD | WS_VISIBLE, 20, 48, 640, 22, hwnd, (HMENU)IDC_STATUS, NULL, NULL);
        SendMessageW(g_status, WM_SETFONT, (WPARAM)g_font, TRUE);
        CreateWindowExW(0, L"STATIC", L"Folder", WS_CHILD | WS_VISIBLE, 20, 84, 80, 20, hwnd, NULL, NULL, NULL);
        g_path = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL, 20, 106, 520, 26,
                                  hwnd, (HMENU)IDC_PATH, NULL, NULL);
        CreateWindowExW(0, L"BUTTON", L"Browse", WS_CHILD | WS_VISIBLE, 550, 104, 110, 28, hwnd, (HMENU)IDC_BROWSE, NULL, NULL);
        CreateWindowExW(0, L"STATIC", L"Hugging Face token (only if you download weights now)", WS_CHILD | WS_VISIBLE, 20, 146,
                         520, 20, hwnd, NULL, NULL, NULL);
        g_token = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_PASSWORD | ES_AUTOHSCROLL, 20, 168,
                                   640, 26, hwnd, (HMENU)IDC_TOKEN, NULL, NULL);
        g_zluda = CreateWindowExW(0, L"BUTTON", L"Install ZLUDA so the RX 6600M can run the CUDA build", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
                                   20, 206, 520, 24, hwnd, (HMENU)IDC_ZLUDA, NULL, NULL);
        g_model = CreateWindowExW(0, L"BUTTON", L"Download Small-Music weights (gated, needs the token)", WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
                                   20, 232, 520, 24, hwnd, (HMENU)IDC_MODEL, NULL, NULL);
        SendMessageW(g_zluda, BM_SETCHECK, BST_CHECKED, 0);
        SendMessageW(g_model, BM_SETCHECK, BST_CHECKED, 0);
        g_progress = CreateWindowExW(0, PROGRESS_CLASSW, NULL, WS_CHILD | WS_VISIBLE, 20, 268, 640, 18, hwnd, (HMENU)IDC_PROGRESS, NULL, NULL);
        SendMessageW(g_progress, PBM_SETRANGE, 0, MAKELPARAM(0, 100));
        g_log = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL,
                                 20, 298, 640, 150, hwnd, (HMENU)IDC_LOG, NULL, NULL);
        g_install = CreateWindowExW(0, L"BUTTON", L"INSTALL", WS_CHILD | WS_VISIBLE, 20, 460, 180, 36, hwnd, (HMENU)IDC_INSTALL, NULL, NULL);
        HWND child = NULL;
        while ((child = FindWindowExW(hwnd, child, NULL, NULL)) != NULL) {
            SendMessageW(child, WM_SETFONT, (WPARAM)g_font, TRUE);
        }
        SendMessageW(title, WM_SETFONT, (WPARAM)g_title, TRUE);
        wchar_t base[MAX_PATH];
        if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, base))) {
            wcscat(base, L"\\Liora");
            SetWindowTextW(g_path, base);
        }
        return 0;
    }
    case WM_ERASEBKGND: {
        RECT rc;
        GetClientRect(hwnd, &rc);
        FillRect((HDC)wp, &rc, g_bg);
        return 1;
    }
    case WM_CTLCOLORSTATIC:
    case WM_CTLCOLORBTN: {
        HDC dc = (HDC)wp;
        SetTextColor(dc, COL_TEXT);
        SetBkColor(dc, RGB(7, 3, 18));
        return (LRESULT)g_bg;
    }
    case WM_CTLCOLOREDIT: {
        HDC dc = (HDC)wp;
        SetTextColor(dc, RGB(246, 238, 254));
        SetBkColor(dc, RGB(22, 10, 40));
        return (LRESULT)g_panel;
    }
    case WM_COMMAND:
        if (LOWORD(wp) == IDC_BROWSE) browse();
        if (LOWORD(wp) == IDC_INSTALL) on_install();
        return 0;
    case WM_LOG: {
        wchar_t *text = (wchar_t *)lp;
        int len = GetWindowTextLengthW(g_log);
        SendMessageW(g_log, EM_SETSEL, len, len);
        SendMessageW(g_log, EM_REPLACESEL, FALSE, (LPARAM)text);
        SendMessageW(g_log, EM_REPLACESEL, FALSE, (LPARAM)L"\r\n");
        SetWindowTextW(g_status, text);
        free(text);
        return 0;
    }
    case WM_PROGRESS:
        SendMessageW(g_progress, PBM_SETPOS, wp, 0);
        return 0;
    case WM_FINISHED:
        InterlockedExchange(&g_busy, 0);
        EnableWindow(g_install, TRUE);
        if (wp == 0) {
            SetWindowTextW(g_status, L"Ready. Launch Liora from the desktop shortcut.");
            MessageBoxW(hwnd, L"Liora is installed.\n\nThe desktop shortcut starts the studio. The first GPU run still needs AMD Adrenalin, and ZLUDA needs the HIP SDK.", L"Liora", MB_OK);
        } else {
            SetWindowTextW(g_status, L"Install failed. The log has the reason.");
        }
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    default:
        break;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show) {
    (void)prev;
    (void)cmd;
    INITCOMMONCONTROLSEX icc = {sizeof(icc), ICC_PROGRESS_CLASS};
    InitCommonControlsEx(&icc);
    g_bg = CreateSolidBrush(RGB(7, 3, 18));
    g_panel = CreateSolidBrush(RGB(22, 10, 40));
    WNDCLASSW wc;
    ZeroMemory(&wc, sizeof(wc));
    wc.lpfnWndProc = wndproc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = g_bg;
    wc.lpszClassName = L"LioraSetup";
    RegisterClassW(&wc);
    HWND hwnd = CreateWindowExW(0, L"LioraSetup", L"Liora Setup", WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
                                 CW_USEDEFAULT, CW_USEDEFAULT, 700, 540, NULL, NULL, inst, NULL);
    ShowWindow(hwnd, show);
    UpdateWindow(hwnd);
    MSG message;
    while (GetMessageW(&message, NULL, 0, 0)) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return 0;
}
