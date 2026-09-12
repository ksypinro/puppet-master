#include <cstdio>

__attribute__((noinline)) void fixture_throw() {
    const int error_code = 17;
    throw error_code; // FIXTURE:CPP_THROW
}

int main() {
    try { fixture_throw(); }
    catch (int code) { std::printf("handled fixture error=%d\n", code); }
    return 0;
}
