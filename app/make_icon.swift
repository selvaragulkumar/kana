// Draws the kana app icon (1024×1024 PNG) with CoreGraphics, from design/kana-app-icon.svg:
// 824 px body on a 1024 canvas (100 px margin), 185 px corner, vertical gradient #1D1D21 → #0A0A0B,
// 2 px rim gradient white 16 % → 3 %, and the bracket mark at translate(256,256) scale(2.56).
//   swift app/make_icon.swift app/icon.png
import AppKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"
let N = 1024
let cs = CGColorSpace(name: CGColorSpace.sRGB)!

func rgb(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255, alpha: a)
}

let ctx = CGContext(data: nil, width: N, height: N, bitsPerComponent: 8, bytesPerRow: 0, space: cs,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
// Work in SVG coordinates (y down).
ctx.translateBy(x: 0, y: CGFloat(N))
ctx.scaleBy(x: 1, y: -1)

// Body with the vertical gradient.
let body = CGPath(roundedRect: CGRect(x: 100, y: 100, width: 824, height: 824), cornerWidth: 185, cornerHeight: 185, transform: nil)
ctx.saveGState()
ctx.addPath(body); ctx.clip()
let bg = CGGradient(colorsSpace: cs, colors: [rgb(0x1D1D21), rgb(0x0A0A0B)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: 0, y: 100), end: CGPoint(x: 0, y: 924), options: [])
ctx.restoreGState()

// Rim: a 2 px stroke filled with a vertical white gradient.
let rimRect = CGRect(x: 101, y: 101, width: 822, height: 822)
let rim = CGPath(roundedRect: rimRect, cornerWidth: 184, cornerHeight: 184, transform: nil)
ctx.saveGState()
ctx.addPath(rim.copy(strokingWithWidth: 2, lineCap: .butt, lineJoin: .miter, miterLimit: 10))
ctx.clip()
let rimGrad = CGGradient(colorsSpace: cs, colors: [rgb(0xFFFFFF, 0.16), rgb(0xFFFFFF, 0.03)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(rimGrad, start: CGPoint(x: 0, y: 100), end: CGPoint(x: 0, y: 924), options: [])
ctx.restoreGState()

// The mark: two corner brackets, square caps, stroke 20 in a 200 viewBox.
ctx.saveGState()
ctx.translateBy(x: 256, y: 256)
ctx.scaleBy(x: 2.56, y: 2.56)
ctx.setLineWidth(20)
ctx.setLineCap(.square)
ctx.setLineJoin(.miter)
ctx.setStrokeColor(rgb(0xFFFFFF))
ctx.move(to: CGPoint(x: 44, y: 128)); ctx.addLine(to: CGPoint(x: 44, y: 44)); ctx.addLine(to: CGPoint(x: 128, y: 44))
ctx.strokePath()
ctx.setStrokeColor(rgb(0xFF4D2E))
ctx.move(to: CGPoint(x: 156, y: 72)); ctx.addLine(to: CGPoint(x: 156, y: 156)); ctx.addLine(to: CGPoint(x: 72, y: 156))
ctx.strokePath()
ctx.restoreGState()

let rep = NSBitmapImageRep(cgImage: ctx.makeImage()!)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print("wrote \(out)")
