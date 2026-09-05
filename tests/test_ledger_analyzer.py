import pytest
from archguard.core.ledger_analyzer import verify_ledger_consistency

class MockDiffResult:
    """Mock 包含 diff.files 结构的类"""
    class File:
        def __init__(self, path):
            self.path = path
            
    def __init__(self, files):
        self.files = [self.File(f) for f in files]

class TestLedgerAnalyzer:
    """测试记账核验"""
    
    def test_perfect_match(self):
        """完全一致时 is_consistent=True"""
        diff = MockDiffResult(["src/main.py", "src/utils.py"])
        events = [{
            "scope": {
                "files_changed": [{"file": "src/main.py"}, {"file": "src/utils.py"}],
                "docs_changed": []
            }
        }]
        
        result = verify_ledger_consistency(diff, events)
        assert result.is_consistent is True
        assert result.consistency_score == 1.0
        assert len(result.undeclared_files) == 0
        assert len(result.phantom_files) == 0
        
    def test_undeclared_files(self):
        """未声明文件检测（瞒报）"""
        diff = MockDiffResult(["src/main.py", "src/secret.py"])
        events = [{
            "scope": {
                "files_changed": [{"file": "src/main.py"}]
            }
        }]
        
        result = verify_ledger_consistency(diff, events)
        assert result.is_consistent is False
        assert "src/secret.py" in result.undeclared_files
        
    def test_phantom_files(self):
        """虚报文件检测"""
        diff = MockDiffResult(["src/main.py"])
        events = [{
            "scope": {
                "files_changed": [{"file": "src/main.py"}, {"file": "src/phantom.py"}]
            }
        }]
        
        result = verify_ledger_consistency(diff, events)
        assert result.is_consistent is False
        assert "src/phantom.py" in result.phantom_files
        
    def test_mixed_scenario(self):
        """混合场景（既有瞒报又有虚报）"""
        diff = MockDiffResult(["src/main.py", "src/undeclared.py"])
        events = [{
            "scope": {
                "files_changed": [{"file": "src/main.py"}, {"file": "src/phantom.py"}]
            }
        }]
        
        result = verify_ledger_consistency(diff, events)
        assert result.is_consistent is False
        assert "src/undeclared.py" in result.undeclared_files
        assert "src/phantom.py" in result.phantom_files
        
    def test_empty_ledger(self):
        """空 ledger 时的处理"""
        diff = MockDiffResult(["src/main.py"])
        events = []
        
        result = verify_ledger_consistency(diff, events)
        assert result.is_consistent is False
        assert "src/main.py" in result.undeclared_files
