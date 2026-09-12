import Foundation

struct FixtureDebit {
    let amount: Int
    let name: String
}

final class FixtureLedger: NSObject {
    var balance = 1000
    var appliedCount = 0
    var descriptionReadCount = 0
    let coupon: String? = nil

    // Deliberately observable: `po`/description evaluation is not a pure read.
    override var description: String {
        descriptionReadCount += 1
        return "FixtureLedger(balance: \(balance), count: \(appliedCount), descriptionReads: \(descriptionReadCount))"
    }

    @inline(never)
    func apply(_ debit: FixtureDebit, index: Int) -> Int {
        let before = balance
        // Same intentional third-debit sign defect as the native C fixture.
        let signedAmount = index == 2 ? debit.amount : -debit.amount
        balance = before + signedAmount // FIXTURE:SWIFT_BEFORE_WRITE
        appliedCount += 1 // FIXTURE:SWIFT_AFTER_WRITE
        return balance // FIXTURE:SWIFT_RETURN
    }
}

@inline(never)
func runFixture() {
    let ledger = FixtureLedger()
    let debits = [
        FixtureDebit(amount: 120, name: "tea"),
        FixtureDebit(amount: 75, name: "paper"),
        FixtureDebit(amount: 40, name: "fruit"),
    ]
    let expected = 765
    var actual = ledger.balance // FIXTURE:SWIFT_READY
    for (index, debit) in debits.enumerated() {
        actual = ledger.apply(debit, index: index) // FIXTURE:SWIFT_CALL
        print("debit=\(index) amount=\(debit.amount) balance=\(actual)")
    }
    print("actual=\(actual) expected=\(expected) mismatch=\(actual != expected)") // FIXTURE:SWIFT_FINAL
}

runFixture()
