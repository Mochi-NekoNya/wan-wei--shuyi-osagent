from pathlib import Path
from backend.app.memory_benchmark import DatasetLoader, BenchmarkRunner
from backend.app.memory_benchmark.report import render_report

results=BenchmarkRunner(DatasetLoader.synthetic(seed=42)).run()
path=Path("reports/egpm_benchmark_report.md"); path.parent.mkdir(exist_ok=True)
path.write_text(render_report(results), encoding="utf-8")
print(path)
