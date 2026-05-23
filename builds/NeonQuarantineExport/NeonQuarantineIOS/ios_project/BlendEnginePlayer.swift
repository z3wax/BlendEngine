import SwiftUI
import WebKit
struct BlendEngineView: UIViewRepresentable { func makeUIView(context: Context) -> WKWebView { let v = WKWebView(); if let url = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "web_player") { v.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent()) }; return v } func updateUIView(_ uiView: WKWebView, context: Context) {} }
@main struct BlendEngineApp: App { var body: some Scene { WindowGroup { BlendEngineView().ignoresSafeArea() } } }
