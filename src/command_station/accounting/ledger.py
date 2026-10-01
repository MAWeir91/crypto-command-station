"""Independent replay of immutable ledger facts, starting at zero."""

from command_station.accounting._exact import ZERO, add
from command_station.accounting.models import (
    AccountBalance,
    AccountingInvariantError,
    AccountView,
    LedgerTransaction,
)
from command_station.domain import AssetSymbol


def replay_ledger(
    transactions: tuple[LedgerTransaction, ...], assets: tuple[AssetSymbol, ...] = ()
) -> AccountView:
    balances = {asset: AccountBalance(asset, ZERO, ZERO) for asset in assets}
    for sequence, transaction in enumerate(transactions, 1):
        if transaction.transaction_id.value != sequence:
            raise AccountingInvariantError("ledger identity sequence is broken")
        for posting in transaction.postings:
            current = balances.get(posting.asset, AccountBalance(posting.asset, ZERO, ZERO))
            balances[posting.asset] = AccountBalance(
                posting.asset,
                add(current.total, posting.balance_delta),
                add(current.reserved, posting.reserved_delta),
            )
    return AccountView(tuple(balances[asset] for asset in sorted(balances, key=lambda a: a.value)))
