"""New cash operations only; never mutate historical fractional payment records."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

def whole(value, *, positive=False):
    try: x=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError): raise ValueError('Enter a valid whole-peso amount')
    if not x.is_finite() or x != x.to_integral_value(): raise ValueError('Amounts must be whole Philippine pesos')
    if x < 0 or (positive and x <= 0): raise ValueError('Enter a positive whole-peso payment')
    return int(x)

def installments(total, count):
    total=whole(total,positive=True)
    try: count=int(count)
    except (ValueError,TypeError): raise ValueError('Invalid installment duration')
    if count<1 or count>240 or count>total: raise ValueError('Duration must be between 1 and 240 and cannot produce zero-peso installments')
    q,rem=divmod(total,count)
    return [q+(i<rem) for i in range(count)]

def authorized_discount(gross, kind, value):
    amount=Decimal(str(gross))
    if kind=='Percentage': amount=amount*Decimal(str(value))/100
    elif kind=='Fixed': amount=Decimal(str(value))
    else: raise ValueError('Unknown authorized discount type')
    if not amount.is_finite() or amount<0: raise ValueError('Invalid discount')
    # Candidate rounding policy, should be approved in HOA resolution before enabling discounts.
    rounded=int(amount.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    if rounded>=gross: raise ValueError('Discount must be less than gross dues')
    return rounded
