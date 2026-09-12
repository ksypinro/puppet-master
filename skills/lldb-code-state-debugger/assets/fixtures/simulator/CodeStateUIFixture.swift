import UIKit

@MainActor
final class FixtureModel {
    private(set) var balance = 1000
    private(set) var tapCount = 0
    private(set) var lastDelta = 0

    @inline(never)
    func debit(amount: Int) {
        tapCount += 1
        let before = balance
        let tapNumber = tapCount
        // Intentional regression: the third tap credits instead of debits.
        let delta = tapNumber == 3 ? amount : -amount
        lastDelta = delta
        balance = before + delta // FIXTURE:UI_BEFORE_WRITE
    } // FIXTURE:UI_MODEL_RETURN

    func reset() {
        balance = 1000
        tapCount = 0
        lastDelta = 0
    }
}

@MainActor
final class FixtureViewController: UIViewController {
    let model = FixtureModel()
    private let balanceLabel = UILabel()
    private let statusLabel = UILabel()

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground

        let title = UILabel()
        title.text = "Code State Fixture"
        title.font = .preferredFont(forTextStyle: .title1)
        title.accessibilityIdentifier = "fixture.title"

        let explanation = UILabel()
        explanation.text = "Artificial local balance. Tap Debit $40 three times."
        explanation.numberOfLines = 0
        explanation.font = .preferredFont(forTextStyle: .body)

        balanceLabel.font = .monospacedDigitSystemFont(ofSize: 32, weight: .semibold)
        balanceLabel.accessibilityIdentifier = "fixture.balance"
        statusLabel.numberOfLines = 0
        statusLabel.font = .preferredFont(forTextStyle: .body)
        statusLabel.accessibilityIdentifier = "fixture.status"

        let debitButton = UIButton(type: .system)
        debitButton.setTitle("Debit $40", for: .normal)
        debitButton.accessibilityIdentifier = "fixture.debit"
        debitButton.accessibilityHint = "Subtracts forty from the artificial balance."
        debitButton.addTarget(self, action: #selector(didTapDebit), for: .touchUpInside)

        let resetButton = UIButton(type: .system)
        resetButton.setTitle("Reset Fixture", for: .normal)
        resetButton.accessibilityIdentifier = "fixture.reset"
        resetButton.addTarget(self, action: #selector(didTapReset), for: .touchUpInside)

        let stack = UIStackView(arrangedSubviews: [title, explanation, balanceLabel, statusLabel, debitButton, resetButton])
        stack.axis = .vertical
        stack.alignment = .fill
        stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -24),
            stack.centerYAnchor.constraint(equalTo: view.safeAreaLayoutGuide.centerYAnchor),
            debitButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 48),
            resetButton.heightAnchor.constraint(greaterThanOrEqualToConstant: 48),
        ])
        render()
    }

    @objc private func didTapDebit() {
        let requestedAmount = 40
        model.debit(amount: requestedAmount) // FIXTURE:UI_ACTION
        render() // FIXTURE:UI_RENDER_AFTER_ACTION
    }

    @objc private func didTapReset() {
        model.reset()
        render()
    }

    private func render() {
        balanceLabel.text = "Balance: $\(model.balance)"
        statusLabel.text = "Taps: \(model.tapCount) · Delta: \(model.lastDelta)"
        balanceLabel.accessibilityValue = String(model.balance)
        statusLabel.accessibilityValue = "taps=\(model.tapCount),delta=\(model.lastDelta)"
    }
}

@main
@MainActor
final class FixtureAppDelegate: UIResponder, UIApplicationDelegate {
    var window: UIWindow?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        let fixtureWindow = UIWindow(frame: UIScreen.main.bounds)
        fixtureWindow.rootViewController = FixtureViewController()
        fixtureWindow.makeKeyAndVisible()
        window = fixtureWindow
        return true
    }
}
