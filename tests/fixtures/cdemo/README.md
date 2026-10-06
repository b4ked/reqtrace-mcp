Test fixture for reqtrace's C/C++ runner. `tests/mini_gtest*` mimic GoogleTest's command line
(`--gtest_list_tests`, `--gtest_filter`, `--gtest_output=json:`) so the runner can be tested
without GoogleTest installed. The crc32c case study uses real GoogleTest.
