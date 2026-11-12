import Foundation
import Security

/// Generic-password items in the login Keychain, service `com.selvaragulkumar.kana`.
enum KeychainStore {
    static let service = "com.selvaragulkumar.kana"
    static let geminiAccount = "GEMINI_API_KEY"

    enum KeychainError: LocalizedError {
        case status(OSStatus)
        var errorDescription: String? {
            switch self {
            case .status(let s):
                let msg = SecCopyErrorMessageString(s, nil) as String? ?? "OSStatus \(s)"
                return "Keychain: \(msg)"
            }
        }
    }

    private static func base(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    static func save(_ value: String, account: String) throws {
        let data = Data(value.utf8)
        let update = SecItemUpdate(base(account) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if update == errSecSuccess { return }
        guard update == errSecItemNotFound else { throw KeychainError.status(update) }
        var add = base(account)
        add[kSecValueData as String] = data
        add[kSecAttrLabel as String] = "kana: \(account)"
        let status = SecItemAdd(add as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError.status(status) }
    }

    /// Reads the secret. May show the system's Keychain prompt if the item was created by a
    /// differently signed build (ad-hoc builds change signature on every rebuild).
    static func read(account: String) -> String? {
        var q = base(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Presence check without touching the secret (attributes only, no access prompt).
    static func exists(account: String) -> Bool {
        var q = base(account)
        q[kSecReturnAttributes as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        return SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess
    }

    @discardableResult
    static func delete(account: String) -> Bool {
        let s = SecItemDelete(base(account) as CFDictionary)
        return s == errSecSuccess || s == errSecItemNotFound
    }
}

/// Where the engine will get its Gemini key from.
enum KeySource: Equatable {
    case keychain
    case dotenv(String)      // path of the .env that has it
    case environment
    case missing

    static func current() -> KeySource {
        if KeychainStore.exists(account: KeychainStore.geminiAccount) { return .keychain }
        if dotenvValue() != nil, let root = EngineLocation.root {
            return .dotenv(root.appendingPathComponent(".env").path)
        }
        if let v = ProcessInfo.processInfo.environment["GEMINI_API_KEY"], !v.isEmpty { return .environment }
        return .missing
    }

    /// GEMINI_API_KEY from `<engine root>/.env`, if set and non-empty. A checkout only: the
    /// bundled engine reads no .env, its key comes from the Keychain.
    static func dotenvValue() -> String? {
        guard let resolved = EngineLocation.resolved, !resolved.bundled,
              let env = Optional(resolved.root.appendingPathComponent(".env")),
              let text = try? String(contentsOf: env, encoding: .utf8) else { return nil }
        for raw in text.split(whereSeparator: \.isNewline) {
            var line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("export ") { line = String(line.dropFirst(7)) }
            let parts = line.split(separator: "=", maxSplits: 1)
            guard parts.count == 2, parts[0].trimmingCharacters(in: .whitespaces) == "GEMINI_API_KEY" else { continue }
            let v = parts[1].trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            if !v.isEmpty { return v }
        }
        return nil
    }

    var label: String {
        switch self {
        case .keychain: return "Keychain"
        case .dotenv: return ".env file"
        case .environment: return "environment"
        case .missing: return "missing"
        }
    }
}
