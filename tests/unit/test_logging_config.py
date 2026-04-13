"""测试日志配置：第三方库日志级别应被抑制为 WARNING"""

import logging


def test_third_party_loggers_suppressed():
    """导入 jfox.cli 后，第三方库的日志级别应为 WARNING 或更高"""
    import jfox.cli  # noqa: F401

    noisy_libs = [
        "sentence_transformers",
        "torch",
        "chromadb",
        "tqdm",
        "urllib3",
        "watchdog",
        "PIL",
    ]
    for lib in noisy_libs:
        lib_logger = logging.getLogger(lib)
        assert (
            lib_logger.level >= logging.WARNING
        ), f"{lib} logger level is {lib_logger.level}, expected >= {logging.WARNING}"


def test_jfox_own_logger_unchanged():
    """jfox 自身的日志不应被抑制（保持继承 root 的 INFO）"""
    import jfox.cli  # noqa: F401

    jfox_logger = logging.getLogger("jfox")
    # jfox logger 未被显式设为 WARNING，保持 NOTSET 并继承 root 的 INFO
    assert (
        jfox_logger.level < logging.WARNING
    ), f"jfox logger level is {jfox_logger.level}, should NOT be suppressed to WARNING"
