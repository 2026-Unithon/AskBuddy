"""병렬 작업의 migration 버전 충돌은 DB 적용 전에 차단한다."""
from collections import Counter
from pathlib import Path


def test_migration_versions_are_unique():
    migrations=Path(__file__).resolve().parents[2]/'supabase/migrations'
    versions=Counter(path.name.split('_',1)[0] for path in migrations.glob('*.sql'))
    assert not {version:count for version,count in versions.items() if count>1}
