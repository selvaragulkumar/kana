// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "Kana",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Kana",
            path: "Sources/Kana"
        )
    ]
)
