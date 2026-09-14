"""为提交相关测试构造最小有效的需求和账本。"""
def prepare_evidence(root):
    import git
    from archguard.sync.prompts import record_prompt
    from archguard.sync.ledger import LedgerManager
    from tests.test_remaining_features import event
    repo=git.Repo(root)
    record_prompt(root,'本测试授权的修改')
    value=event()
    value['git']={'base_commit':repo.head.commit.hexsha if repo.head.is_valid() else None}
    LedgerManager(root).append_event(value)
