#!/usr/bin/env bash
# 容器首次启动后补齐种子数据（宿主 .deploy 挂载会遮住镜像内置的 DB）
set -e
cd /srv/omnitest/c/backend
python scripts/import_kb_from_scenes.py || true
python - <<'PY'
import sys
sys.path.insert(0, "/srv/omnitest/c/backend")
from app.db.session import Session, engine
from app.services.credits_service import CreditsService
from app.services.local_admin_service import seed_local_admin
with Session(engine) as s:
    CreditsService.seed_initial_data(s); s.commit()
seed_local_admin()
print("post-init done")
PY
