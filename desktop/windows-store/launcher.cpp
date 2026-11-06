// The Store package contains the current DMate executable and its own WebView2
// runtime. No installer, elevation, profile migration or runtime download runs.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string>
#include <vector>

namespace {
bool regularFile(const std::wstring& path) {
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

int fail(const wchar_t* english, const wchar_t* chinese) {
    const bool useChinese = PRIMARYLANGID(GetUserDefaultUILanguage()) == LANG_CHINESE;
    MessageBoxW(nullptr, useChinese ? chinese : english, L"DMate", MB_OK | MB_ICONERROR);
    return 1;
}

std::wstring executableDirectory() {
    std::vector<wchar_t> path(1024);
    for (;;) {
        const DWORD length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
        if (!length) return {};
        if (length < path.size()) {
            const std::wstring value(path.data(), length);
            const auto separator = value.find_last_of(L"\\/");
            return separator == std::wstring::npos ? std::wstring{} : value.substr(0, separator);
        }
        if (path.size() >= 32768) return {};
        path.resize(path.size() * 2);
    }
}
}  // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR arguments, int showCommand) {
    const std::wstring root = executableDirectory();
    if (root.empty()) {
        return fail(L"DMate could not locate its installed files.", L"DMate 无法找到已安装的程序文件。");
    }
    const std::wstring appDirectory = root + L"\\App";
    const std::wstring executable = appDirectory + L"\\dmate-desktop.exe";
    const std::wstring runtime = appDirectory + L"\\WebView2";
    if (!regularFile(executable) || !regularFile(runtime + L"\\msedgewebview2.exe")) {
        return fail(L"DMate's installed files are incomplete. Reinstall DMate from Microsoft Store.",
                    L"DMate 的安装文件不完整。请从 Microsoft Store 重新安装 DMate。");
    }
    if (!SetEnvironmentVariableW(L"WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", runtime.c_str())) {
        return fail(L"DMate could not initialize its included WebView2 runtime.",
                    L"DMate 无法初始化内置的 WebView2 运行时。");
    }
    std::wstring command = L"\"" + executable + L"\"";
    if (arguments && *arguments) command += std::wstring(L" ") + arguments;
    std::vector<wchar_t> mutableCommand(command.begin(), command.end());
    mutableCommand.push_back(L'\0');
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = static_cast<WORD>(showCommand);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(executable.c_str(), mutableCommand.data(), nullptr, nullptr, FALSE,
                        0, nullptr, appDirectory.c_str(), &startup, &process)) {
        return fail(L"DMate could not start. Reinstall DMate from Microsoft Store if the problem continues.",
                    L"DMate 无法启动。如问题持续，请从 Microsoft Store 重新安装 DMate。");
    }
    CloseHandle(process.hThread);
    const DWORD waitResult = WaitForSingleObject(process.hProcess, INFINITE);
    DWORD exitCode = 1;
    if (waitResult == WAIT_OBJECT_0) GetExitCodeProcess(process.hProcess, &exitCode);
    CloseHandle(process.hProcess);
    return static_cast<int>(exitCode);
}
