#include <windows.h>
#include <shellapi.h>
#include <string.h>
#include <wchar.h>

#define BUFFER_SIZE 32768

static int run_and_wait(const wchar_t *command, DWORD flags, DWORD *exit_code) {
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    wchar_t mutable_command[BUFFER_SIZE];
    startup.cb = sizeof(startup);
    wcsncpy(mutable_command, command, BUFFER_SIZE - 1);
    mutable_command[BUFFER_SIZE - 1] = L'\0';
    if (!CreateProcessW(NULL, mutable_command, NULL, NULL, FALSE, flags, NULL, NULL, &startup, &process)) {
        return 0;
    }
    WaitForSingleObject(process.hProcess, INFINITE);
    GetExitCodeProcess(process.hProcess, exit_code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 1;
}

static int start_process(const wchar_t *command) {
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    wchar_t mutable_command[BUFFER_SIZE];
    startup.cb = sizeof(startup);
    wcsncpy(mutable_command, command, BUFFER_SIZE - 1);
    mutable_command[BUFFER_SIZE - 1] = L'\0';
    if (!CreateProcessW(NULL, mutable_command, NULL, NULL, FALSE, CREATE_NEW_CONSOLE, NULL, NULL, &startup, &process)) {
        return 0;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 1;
}

static void show_error(const wchar_t *message) {
    MessageBoxW(NULL, message, L"ASOLAR ESET Tracker Manager", MB_OK | MB_ICONERROR | MB_TOPMOST);
}

static int open_cloud_client(void) {
    HANDLE file = CreateFileW(L"server-url.txt", GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    char input[2048];
    wchar_t url[2048];
    DWORD read = 0;
    size_t length;
    if (file == INVALID_HANDLE_VALUE) return 0;
    if (!ReadFile(file, input, sizeof(input) - 1, &read, NULL)) {
        CloseHandle(file);
        show_error(L"Nie można odczytać pliku server-url.txt.");
        return -1;
    }
    CloseHandle(file);
    input[read] = '\0';
    while (read > 0 && (input[read - 1] == '\r' || input[read - 1] == '\n' || input[read - 1] == ' ' || input[read - 1] == '\t')) input[--read] = '\0';
    length = strlen(input);
    if (!length || (strncmp(input, "https://", 8) != 0 && strncmp(input, "http://", 7) != 0)) {
        show_error(L"Plik server-url.txt musi zawierać pełny adres zaczynający się od https:// lub http://.");
        return -1;
    }
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, input, -1, url, 2048)) {
        show_error(L"Adres w server-url.txt nie jest prawidłowym tekstem UTF-8.");
        return -1;
    }
    if ((INT_PTR)ShellExecuteW(NULL, L"open", url, NULL, NULL, SW_SHOWNORMAL) <= 32) {
        show_error(L"Nie udało się otworzyć adresu aplikacji chmurowej.");
        return -1;
    }
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    wchar_t executable_path[BUFFER_SIZE];
    wchar_t *last_separator;
    DWORD exit_code = 1;
    (void)instance; (void)previous; (void)arguments; (void)show;

    if (!GetModuleFileNameW(NULL, executable_path, BUFFER_SIZE)) {
        show_error(L"Nie można ustalić folderu programu.");
        return 1;
    }
    last_separator = wcsrchr(executable_path, L'\\');
    if (!last_separator) {
        show_error(L"Nieprawidłowa ścieżka programu.");
        return 1;
    }
    *last_separator = L'\0';
    if (!SetCurrentDirectoryW(executable_path)) {
        show_error(L"Nie można otworzyć folderu programu.");
        return 1;
    }

    int cloud_client = open_cloud_client();
    if (cloud_client > 0) return 0;
    if (cloud_client < 0) return 6;

    if (!run_and_wait(L"py -3.11 --version", CREATE_NO_WINDOW, &exit_code) || exit_code != 0) {
        show_error(L"Nie znaleziono Pythona 3.11. Zainstaluj Python 3.11 z python.org razem z programem Python Launcher (py), a następnie ponownie uruchom ASOLAR.exe.");
        return 2;
    }
    if (GetFileAttributesW(L"frontend\\dist\\index.html") == INVALID_FILE_ATTRIBUTES) {
        show_error(L"Brak zbudowanego interfejsu. Rozpakuj pełną paczkę ASOLAR do nowego folderu.");
        return 3;
    }

    if (GetFileAttributesW(L"runtime-packages\\.asolar-deps-v3") == INVALID_FILE_ATTRIBUTES) {
        CreateDirectoryW(L"runtime-packages", NULL);
        MessageBoxW(NULL, L"Pierwsze uruchomienie przygotuje wymagane składniki. Może to potrwać kilka minut i wymaga połączenia z Internetem.", L"ASOLAR — pierwsze uruchomienie", MB_OK | MB_ICONINFORMATION | MB_TOPMOST);
        if (!run_and_wait(L"py -3.11 -m pip install --upgrade --target runtime-packages -r requirements.txt", CREATE_NEW_CONSOLE, &exit_code) || exit_code != 0) {
            show_error(L"Nie udało się zainstalować składników programu. Sprawdź Internet oraz instalację Pythona 3.11.");
            return 4;
        }
        HANDLE marker = CreateFileW(L"runtime-packages\\.asolar-deps-v3", GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_HIDDEN, NULL);
        if (marker != INVALID_HANDLE_VALUE) CloseHandle(marker);
    }

    wchar_t runtime_path[BUFFER_SIZE];
    wchar_t previous_python_path[BUFFER_SIZE];
    DWORD previous_length = GetEnvironmentVariableW(L"PYTHONPATH", previous_python_path, BUFFER_SIZE);
    if (previous_length > 0 && previous_length < BUFFER_SIZE) {
        _snwprintf(runtime_path, BUFFER_SIZE - 1, L"%ls\\runtime-packages;%ls", executable_path, previous_python_path);
    } else {
        _snwprintf(runtime_path, BUFFER_SIZE - 1, L"%ls\\runtime-packages", executable_path);
    }
    runtime_path[BUFFER_SIZE - 1] = L'\0';
    SetEnvironmentVariableW(L"PYTHONPATH", runtime_path);
    SetEnvironmentVariableW(L"ASOLAR_DESKTOP_EXE", L"1");

    if (!start_process(L"py -3.11 desktop.py")) {
        show_error(L"Nie udało się uruchomić aplikacji. Użyj awaryjnie pliku Uruchom-Windows.bat.");
        return 5;
    }
    return 0;
}
