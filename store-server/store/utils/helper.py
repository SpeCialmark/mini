

def move(a, i, j):
    if i == j:
        return a
    b = []
    for index, x in enumerate(a):
        if len(b) == j:
            b.append(a[i])

        if index != i:
            b.append(x)

        if len(b) == j:
            b.append(a[i])
    return b
