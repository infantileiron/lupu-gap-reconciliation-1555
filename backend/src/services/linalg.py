import math

def zeros(n,m=None):
    m = n if m is None else m
    return [[0.0]*m for _ in range(n)]

def transpose(a):
    return [list(row) for row in zip(*a)]

def matmul(a,b):
    bt=transpose(b);return [[sum(x*y for x,y in zip(ra,cb)) for cb in bt] for ra in a]

def matvec(a,v):
    return [sum(x*y for x,y in zip(row,v)) for row in a]

def chol(a):
    n=len(a);L=zeros(n)
    for i in range(n):
        for j in range(i+1):
            s=a[i][j]-sum(L[i][k]*L[j][k] for k in range(j))
            if i==j:
                if not math.isfinite(s) or s<=0.:raise ValueError('正定矩阵分解失败')
                L[i][j]=math.sqrt(s)
            else:L[i][j]=s/L[j][j]
    return L

def chol_solve(L,b):
    n=len(L);y=[0.0]*n
    for i in range(n):
        y[i]=(b[i]-sum(L[i][k]*y[k] for k in range(i)))/L[i][i]
    x=[0.0]*n
    for i in range(n-1,-1,-1):
        x[i]=(y[i]-sum(L[k][i]*x[k] for k in range(i+1,n)))/L[i][i]
    return x

def solve_spd(a,b):
    return chol_solve(chol(a),b)

def invert_spd(a):
    L=chol(a);n=len(a);columns=[]
    for j in range(n):
        e=[0.0]*n;e[j]=1.0;columns.append(chol_solve(L,e))
    return [[columns[j][i] for j in range(n)] for i in range(n)]

def jittered_invert(a,factor=1e-12):
    try:return invert_spd(a)
    except ValueError:
        n=len(a);b=[row[:] for row in a]
        scale=max(abs(a[i][i]) for i in range(n)) or 1.0
        for i in range(n):b[i][i]+=factor*scale
        return invert_spd(b)
