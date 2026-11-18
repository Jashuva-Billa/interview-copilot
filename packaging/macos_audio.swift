import AVFoundation
import CoreGraphics
import CoreMedia
import Foundation
import ScreenCaptureKit

@available(macOS 13.0, *)
final class AudioOutput: NSObject, SCStreamOutput, SCStreamDelegate {
    func stream(_ stream: SCStream, didOutputSampleBuffer buffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, buffer.isValid,
              let description = buffer.formatDescription else { return }
        let format = AVAudioFormat(cmAudioFormatDescription: description)
        guard let audio = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(buffer.numSamples)) else { return }
        audio.frameLength = audio.frameCapacity
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(
            buffer, at: 0, frameCount: Int32(buffer.numSamples), into: audio.mutableAudioBufferList
        ) == noErr, let samples = audio.floatChannelData?[0] else { return }
        FileHandle.standardOutput.write(Data(bytes: samples, count: Int(audio.frameLength) * MemoryLayout<Float>.size))
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        FileHandle.standardError.write(Data("System audio capture stopped.\n".utf8))
        exit(1)
    }
}

@main
struct CaptureAudio {
    static func main() async {
        guard #available(macOS 13.0, *) else { exit(1) }
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.first else { exit(1) }
            let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true
            config.sampleRate = 16_000
            config.channelCount = 1
            config.width = 2
            config.height = 2
            let output = AudioOutput()
            let stream = SCStream(filter: filter, configuration: config, delegate: output)
            try stream.addStreamOutput(output, type: .audio, sampleHandlerQueue: DispatchQueue(label: "capture-audio"))
            try await stream.startCapture()
            FileHandle.standardError.write(Data("READY\n".utf8))
            while !Task.isCancelled {
                try await Task.sleep(nanoseconds: 1_000_000_000)
            }
        } catch {
            FileHandle.standardError.write(Data("Allow Screen & System Audio Recording for Interview Copilot in System Settings.\n".utf8))
            exit(1)
        }
    }
}
