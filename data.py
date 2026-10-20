import sqlite3

class Data:
    VERSION = "1.0"

    def __init__(self, filename):
        self._db = sqlite3.connect(filename)

        # Verify DB integrity
        cur = self._db.cursor()
        try:
            res = cur.execute("select version from metadata")
            version = res.fetchone()
        except Exception as e:
            print("DEBUG: Version not found")
            print(e)
            version = None

        if version is None or version[0] != self.VERSION:
            print(f"DEBUG: Version is {version}")
            # Initialize the database from scratch, in the future we will worry about migrations from earlier versions
            cur.execute("create table categories(\
                        id integer primary key asc,\
                        name text unique)"
                        )
            cur.execute("create table cashflow(\
                        id integer primary key asc, \
                        amount integer, \
                        description text,\
                        category_id integer, \
                        timestamp int, \
                        foreign key(category_id) references categories(id))"
                        )
            cur.execute("create table periods(\
                        id integer primary key asc,\
                        start_date integer,\
                        end_date integer)"
                       )
            cur.execute("create table budgets(\
                        id integer primary key asc,\
                        amount integer,\
                        category_id integer,\
                        period_id integer,\
                        foreign key(category_id) references categories(id),\
                        foreign key(period_id) references periods(id))"
                        )
            cur.execute("create table metadata(version text)")
            cur.execute("insert into metadata(version) values (?)", (self.VERSION,))
            self._db.commit()

    def get_period(self, date):
        cur = self._db.cursor()
        res = cur.execute("select id, start_date, end_date from periods where start_date <= ? and end_date >= ?", (date, date))
        values = res.fetchone()
        return values

    def add_period(self, start_date, end_date):
        cur = self._db.cursor()
        cur.execute("insert into periods(start_date, end_date) values (?, ?)", (start_date, end_date))
        self._db.commit()

    def add_category(self, name):
        success = False
        try:
            cur = self._db.cursor()
            cur.execute("insert into categories(name) values (?)", (name,))
            self._db.commit()
            success = True
        except:
            pass
        return success

    def get_categories(self):
        cur = self._db.cursor()
        res = cur.execute("select id, name from categories")
        values = res.fetchall()
        prettier = [{'id': v[0], 'name': v[1]} for v in values]
        return prettier
    
        





