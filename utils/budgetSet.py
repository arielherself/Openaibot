RESET_TIME = 5

def db() -> list:
    try:
        result = []
        with open('list.plain') as f:
            lines = f.readlines()
        for line in lines:
            if line.strip():
                result.append(line.strip().split(' '))
        return result
    except:
        return []

def detect(uid: any) -> bool:
    users = [item[0] for item in db()]
    if str(uid) in users:
        return True
    else:
        return False

def write(uid: any) -> bool:
    try:
        if len(db()) == 0:
            with open('list.plain', 'w') as f:
                print(str(uid) + ' 1', file=f)
        else:
            with open('list.plain', 'a') as f:
                print(str(uid) + ' 1', file=f)
        return True
    except:
        return False

def delete(uid: any) -> bool:
    try:
        a = db()
        users = [item[0] for item in a]
        while str(uid) in users:
            a.pop(users.index(str(uid)))
            users.pop(users.index(str(uid)))
        with open('list.plain', 'w') as f:
            for item in a:
                print(' '.join(item), file=f)
        return True
    except:
        return False

def doorman(uid: any) -> bool:
    try:
        result: bool
        a = db()
        users = [item[0] for item in a]
        if str(uid) in users:
            count = int(a[users.index(str(uid))][1]) + 1
            if count <= RESET_TIME + 10:
                a[users.index(str(uid))][1] = str(count)
                result = True
            else:
                a[users.index(str(uid))][1] = '1'
                result = False
        else:
            result = True
        with open('list.plain', 'w') as f:
            for item in a:
                print(' '.join(item), file=f)
        return result
    except:
        return True
