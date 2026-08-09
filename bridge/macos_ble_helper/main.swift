import CoreBluetooth
import Darwin
import Foundation

private let serialServiceUUID = CBUUID(string: "8FE5B3D5-2E7F-4A98-2A48-7ACC60FE0000")
private let serialTxUUID = CBUUID(string: "19ED82AE-ED21-4C9D-4145-228E61FE0000")
private let serialRxUUID = CBUUID(string: "19ED82AE-ED21-4C9D-4145-228E62FE0000")
private let codexAdvertisementMarker = Data("CODEXMON1".utf8)
private let openChatGPTAction = "ACT OPEN"
private let chatGPTBundleIdentifier = "com.openai.codex"

private struct Request: Decodable {
    let id: Int
    let payload: String
}

private final class FlipperBleClient: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private let targetName: String
    private let inputHandle: FileHandle
    private let outputHandle: FileHandle
    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var rxCharacteristic: CBCharacteristic?
    private var txCharacteristic: CBCharacteristic?
    private var pending: [Request] = []
    private var active: Request?
    private var replayPending = false
    private var replayActive = false
    private var activePayload: String?
    private var cachedPayloads: [String: String] = [:]
    private var replayQueue: [String] = []
    private var responseBuffer = Data()
    private var inputBuffer = Data()
    private var acknowledgementTimer: Timer?

    init(targetName: String, inputHandle: FileHandle, outputHandle: FileHandle) {
        self.targetName = targetName
        self.inputHandle = inputHandle
        self.outputHandle = outputHandle
        super.init()
    }

    func start() {
        central = CBCentralManager(delegate: self, queue: .main)
        inputHandle.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty {
                DispatchQueue.main.async {
                    self?.shutdown()
                    exit(0)
                }
                return
            }
            DispatchQueue.main.async {
                self?.consumeInput(data)
            }
        }
    }

    private func consumeInput(_ data: Data) {
        inputBuffer.append(data)
        while let newline = inputBuffer.firstIndex(of: 0x0A) {
            let line = inputBuffer.prefix(upTo: newline)
            inputBuffer.removeSubrange(...newline)
            guard !line.isEmpty else { continue }
            do {
                let request = try JSONDecoder().decode(Request.self, from: Data(line))
                guard request.id >= 0 else { throw HelperError.invalidRequest }
                guard request.payload.utf8.count <= 191 else { throw HelperError.payloadTooLarge }
                replayPending = false
                replayQueue.removeAll()
                pending.append(request)
                pump()
            } catch {
                log("invalid request: \(error)")
            }
        }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        log("central state \(central.state.rawValue)")
        switch central.state {
        case .poweredOn:
            pump()
        case .poweredOff:
            failAll("macOS Bluetooth is turned off")
        case .unauthorized:
            failAll("Bluetooth permission is not granted")
        case .unsupported:
            failAll("Bluetooth LE is not supported")
        default:
            break
        }
    }

    private func pump() {
        guard active == nil, !replayActive else { return }
        let hasReplay = replayPending && !replayQueue.isEmpty
        guard !pending.isEmpty || hasReplay else { return }
        if isReady, let peripheral, let rxCharacteristic {
            if !pending.isEmpty {
                let request = pending.removeFirst()
                beginWrite(request.payload, request: request, peripheral: peripheral, rx: rxCharacteristic)
            } else if !replayQueue.isEmpty {
                let payload = replayQueue.removeFirst()
                replayPending = !replayQueue.isEmpty
                log("replaying cached monitor data after FAP reconnect")
                beginWrite(payload, request: nil, peripheral: peripheral, rx: rxCharacteristic)
            }
            return
        }

        guard central.state == .poweredOn else { return }
        if let peripheral {
            if peripheral.state == .disconnected {
                central.connect(peripheral)
            }
            return
        }
        if !central.isScanning {
            log("scanning for Codex \(targetName)")
            central.scanForPeripherals(withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
        }
    }

    private func beginWrite(
        _ payload: String,
        request: Request?,
        peripheral: CBPeripheral,
        rx: CBCharacteristic
    ) {
        guard let bytes = payload.data(using: .ascii) else {
            if let request { respond(request, status: "error", error: "payload is not ASCII") }
            pump()
            return
        }
        guard bytes.count <= peripheral.maximumWriteValueLength(for: .withResponse) else {
            if let request {
                respond(request, status: "error", error: "payload exceeds negotiated BLE MTU")
            }
            pump()
            return
        }
        active = request
        replayActive = request == nil
        activePayload = payload
        responseBuffer.removeAll(keepingCapacity: true)
        acknowledgementTimer?.invalidate()
        acknowledgementTimer = Timer.scheduledTimer(withTimeInterval: 8, repeats: false) {
            [weak self] _ in
            self?.finishActive(error: "Flipper BLE acknowledgement timed out")
        }
        peripheral.writeValue(bytes, for: rx, type: .withResponse)
    }

    private var isReady: Bool {
        peripheral?.state == .connected &&
            rxCharacteristic != nil &&
            txCharacteristic?.isNotifying == true
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let advertisedName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let candidates = [peripheral.name, advertisedName].compactMap { $0 }
        let manufacturerData = advertisementData[CBAdvertisementDataManufacturerDataKey] as? Data
        let isCodexMonitor = manufacturerData?.range(of: codexAdvertisementMarker) != nil
        if candidates.contains(where: { $0.localizedCaseInsensitiveContains(targetName) }) {
            log("saw \(candidates.joined(separator: ", ")) codex=\(isCodexMonitor)")
        }
        guard isCodexMonitor else { return }
        guard candidates.contains(where: { $0.localizedCaseInsensitiveContains(targetName) }) else {
            return
        }
        central.stopScan()
        self.peripheral = peripheral
        peripheral.delegate = self
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        log("connected to \(peripheral.name ?? targetName)")
        peripheral.delegate = self
        peripheral.discoverServices([serialServiceUUID])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        self.peripheral = nil
        failFirstPending("BLE connection failed: \(error?.localizedDescription ?? "unknown error")")
        pump()
    }

    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        rxCharacteristic = nil
        txCharacteristic = nil
        self.peripheral = nil
        if active != nil || replayActive {
            finishActive(error: "Flipper BLE disconnected")
        }
        if !cachedPayloads.isEmpty {
            prepareReplayQueue()
            log("FAP disconnected; waiting for Codex BLE advertisement")
        }
        pump()
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            disconnectWithError("BLE service discovery failed: \(error.localizedDescription)")
            return
        }
        guard let service = peripheral.services?.first(where: { $0.uuid == serialServiceUUID }) else {
            disconnectWithError("Flipper BLE Serial service was not found")
            return
        }
        peripheral.discoverCharacteristics([serialTxUUID, serialRxUUID], for: service)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        if let error {
            disconnectWithError("BLE characteristic discovery failed: \(error.localizedDescription)")
            return
        }
        for characteristic in service.characteristics ?? [] {
            if characteristic.uuid == serialRxUUID {
                rxCharacteristic = characteristic
            } else if characteristic.uuid == serialTxUUID {
                txCharacteristic = characteristic
            }
        }
        guard rxCharacteristic != nil, let txCharacteristic else {
            disconnectWithError("Flipper BLE Serial RX/TX characteristics were not found")
            return
        }
        peripheral.setNotifyValue(true, for: txCharacteristic)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            disconnectWithError("BLE notification setup failed: \(error.localizedDescription)")
            return
        }
        pump()
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didWriteValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            finishActive(error: "BLE write failed: \(error.localizedDescription)")
        }
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            finishActive(error: "BLE acknowledgement failed: \(error.localizedDescription)")
            return
        }
        guard characteristic.uuid == serialTxUUID, let value = characteristic.value else { return }
        if handleAction(value) { return }
        responseBuffer.append(value)
        let normalized = String(data: responseBuffer, encoding: .utf8)?.lowercased() ?? ""
        if normalized.contains("ok\r\n") {
            finishActive(error: nil)
        } else if normalized.contains("err ") {
            finishActive(error: "Flipper rejected BLE payload")
        }
    }

    private func handleAction(_ value: Data) -> Bool {
        guard let message = String(data: value, encoding: .ascii)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            message == openChatGPTAction
        else {
            return false
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-b", chatGPTBundleIdentifier]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            log("requested ChatGPT activation")
        } catch {
            log("unable to activate ChatGPT: \(error.localizedDescription)")
        }
        return true
    }

    private func finishActive(error: String?) {
        acknowledgementTimer?.invalidate()
        acknowledgementTimer = nil
        let request = active
        let wasReplay = replayActive
        let payload = activePayload
        guard request != nil || wasReplay else { return }
        active = nil
        replayActive = false
        activePayload = nil
        if let error {
            if let request { respond(request, status: "error", error: error) }
            if wasReplay {
                if let payload { replayQueue.insert(payload, at: 0) }
                replayPending = true
                log("cached monitor replay failed: \(error)")
            }
        } else {
            if let request {
                cacheAcknowledgedPayload(request.payload)
                respond(request, status: "ok", error: nil)
            } else {
                if !replayPending && replayQueue.isEmpty {
                    log("cached monitor replay acknowledged")
                }
            }
        }
        pump()
    }

    private func failFirstPending(_ message: String) {
        guard !pending.isEmpty else { return }
        respond(pending.removeFirst(), status: "error", error: message)
    }

    private func failAll(_ message: String) {
        if active != nil || replayActive { finishActive(error: message) }
        while !pending.isEmpty {
            respond(pending.removeFirst(), status: "error", error: message)
        }
        if !cachedPayloads.isEmpty { prepareReplayQueue() }
    }

    private func disconnectWithError(_ message: String) {
        failFirstPending(message)
        if let peripheral {
            central.cancelPeripheralConnection(peripheral)
        }
    }

    private func respond(_ request: Request, status: String, error: String?) {
        var object: [String: Any] = ["id": request.id, "status": status]
        if let error { object["error"] = error }
        guard var data = try? JSONSerialization.data(withJSONObject: object) else { return }
        data.append(0x0A)
        outputHandle.write(data)
    }

    private func payloadKey(_ payload: String) -> String {
        let fields = payload.split(separator: " ")
        guard let command = fields.first.map(String.init) else { return payload }
        if command == "codextask",
           let slot = fields.dropFirst().first(where: { $0.hasPrefix("k=") }) {
            return "codextask:\(slot.dropFirst(2))"
        }
        return command
    }

    private func cacheAcknowledgedPayload(_ payload: String) {
        cachedPayloads[payloadKey(payload)] = payload
        let fields = payload.split(separator: " ")
        guard fields.first == "codextasks",
              let countField = fields.dropFirst().first(where: { $0.hasPrefix("n=") }),
              let count = Int(countField.dropFirst(2)),
              count >= 0,
              count <= 16
        else {
            return
        }
        for slot in count..<16 {
            let key = "codextask:" + String(slot, radix: 36).uppercased()
            cachedPayloads.removeValue(forKey: key)
        }
    }

    private func prepareReplayQueue() {
        let taskKeys = (0..<16).map {
            "codextask:" + String($0, radix: 36).uppercased()
        }
        let preferred = ["codexmon", "codexuse", "codextasks"] + taskKeys
        replayQueue = preferred.compactMap { cachedPayloads[$0] }
        let known = Set(preferred)
        replayQueue.append(
            contentsOf: cachedPayloads
                .filter { !known.contains($0.key) }
                .sorted { $0.key < $1.key }
                .map(\.value)
        )
        replayPending = !replayQueue.isEmpty
    }

    private func log(_ message: String) {
        if let data = ("Codex Flipper BLE: \(message)\n").data(using: .utf8) {
            FileHandle.standardError.write(data)
        }
    }

    private func shutdown() {
        inputHandle.readabilityHandler = nil
        acknowledgementTimer?.invalidate()
        replayPending = false
        replayActive = false
        activePayload = nil
        cachedPayloads.removeAll()
        replayQueue.removeAll()
        if central.isScanning { central.stopScan() }
        if let peripheral, peripheral.state != .disconnected {
            central.cancelPeripheralConnection(peripheral)
        }
        try? inputHandle.close()
        try? outputHandle.close()
    }

    private enum HelperError: Error {
        case invalidRequest
        case payloadTooLarge
    }
}

private func argumentValue(after flag: String) -> String? {
    guard let index = CommandLine.arguments.firstIndex(of: flag) else { return nil }
    let valueIndex = CommandLine.arguments.index(after: index)
    guard valueIndex < CommandLine.arguments.endIndex else { return nil }
    return CommandLine.arguments[valueIndex]
}

private func connectUnixSocket(_ path: String) -> (FileHandle, FileHandle)? {
    let descriptor = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
    guard descriptor >= 0 else { return nil }

    var address = sockaddr_un()
    address.sun_family = sa_family_t(AF_UNIX)
    let pathBytes = Array(path.utf8) + [0]
    let pathCapacity = MemoryLayout.size(ofValue: address.sun_path)
    guard pathBytes.count <= pathCapacity else {
        Darwin.close(descriptor)
        return nil
    }
    withUnsafeMutableBytes(of: &address.sun_path) { buffer in
        buffer.initializeMemory(as: UInt8.self, repeating: 0)
        buffer.copyBytes(from: pathBytes)
    }
    let addressLength = socklen_t(MemoryLayout<sockaddr_un>.size)
    address.sun_len = UInt8(addressLength)
    let connected = withUnsafePointer(to: &address) { pointer in
        pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { socketAddress in
            Darwin.connect(descriptor, socketAddress, addressLength)
        }
    }
    guard connected == 0 else {
        Darwin.close(descriptor)
        return nil
    }
    let outputDescriptor = Darwin.dup(descriptor)
    guard outputDescriptor >= 0 else {
        Darwin.close(descriptor)
        return nil
    }
    return (
        FileHandle(fileDescriptor: descriptor, closeOnDealloc: true),
        FileHandle(fileDescriptor: outputDescriptor, closeOnDealloc: true)
    )
}

guard let targetName = argumentValue(after: "--name"), !targetName.isEmpty else {
    FileHandle.standardError.write(Data("Usage: codex-flipper-ble --name DEVICE\n".utf8))
    exit(2)
}

private let handles: (FileHandle, FileHandle)
if let socketPath = argumentValue(after: "--socket") {
    guard let socketHandles = connectUnixSocket(socketPath) else {
        FileHandle.standardError.write(Data("Unable to connect to monitor socket\n".utf8))
        exit(3)
    }
    handles = socketHandles
} else {
    handles = (FileHandle.standardInput, FileHandle.standardOutput)
}

private let client = FlipperBleClient(
    targetName: targetName,
    inputHandle: handles.0,
    outputHandle: handles.1)
client.start()
RunLoop.main.run()
