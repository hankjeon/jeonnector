"""테스트 공통 설정."""

import os

# 단독 실행과 전체 실행이 같은 Qt 플랫폼(화면 없는 offscreen)에서 동작하도록 고정한다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
