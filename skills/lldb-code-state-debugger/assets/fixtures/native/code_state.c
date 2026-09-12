#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

/* Artificial, process-local data. No files, network, timers, or user data. */
volatile int32_t fixture_balance = 1000;
unsigned char fixture_bytes[8] = {0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77};

typedef struct {
    int32_t amount;
    const char *name;
} FixtureDebit;

__attribute__((noinline)) static int32_t apply_debit(FixtureDebit debit, int index) {
    int32_t before = fixture_balance;
    /* Deliberate sign defect only on the third debit; do not "fix" this fixture. */
    int32_t signed_amount = index == 2 ? debit.amount : -debit.amount;
    fixture_balance = before + signed_amount; /* FIXTURE:C_BEFORE_WRITE */
    int32_t after = fixture_balance; /* FIXTURE:C_AFTER_WRITE */
    return after; /* FIXTURE:C_RETURN */
}

int main(void) {
    const FixtureDebit debits[3] = {{120, "tea"}, {75, "paper"}, {40, "fruit"}};
    const int32_t expected = 765;
    int32_t actual = fixture_balance; /* FIXTURE:C_READY */
    for (int index = 0; index < 3; ++index) {
        FixtureDebit debit = debits[index];
        actual = apply_debit(debit, index); /* FIXTURE:C_CALL */
        printf("debit=%d amount=%" PRId32 " balance=%" PRId32 "\n", index, debit.amount, actual);
    }
    printf("actual=%" PRId32 " expected=%" PRId32 " mismatch=%d\n", actual, expected, actual != expected); /* FIXTURE:C_FINAL */
    return 0;
}
