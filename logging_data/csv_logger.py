from pathlib import Path
import csv


class CsvLogger:
    def __init__(self, path, fieldnames):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fieldnames = fieldnames
        self._f = self.path.open('w', newline='', encoding='utf-8')
        self._writer = csv.DictWriter(self._f, fieldnames=fieldnames)
        self._writer.writeheader()

    def write(self, row):
        self._writer.writerow(row)

    def close(self):
        self._f.close()
