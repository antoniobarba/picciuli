from datetime import datetime
from data import Data
d = Data("data/aaatest.db")
d.add_category("prova")
d.add_category("miao")
print(d.get_categories())

empty = Data("data/empty.db")
print(empty.get_categories())

periods = Data("data/periods.db")
periods.add_period(datetime(2026, 10, 1), datetime(2026, 10, 31) )
print(periods.get_period(datetime(2026, 10, 3)))


