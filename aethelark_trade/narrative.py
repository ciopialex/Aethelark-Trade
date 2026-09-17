from dataclasses import dataclass
from typing import Optional, List

@dataclass
class InsiderTransaction:
    # Minimal interface needed for narrative generation
    # In real usage, this will receive the full object, but duck typing works
    insider_name: str
    insider_title: str
    issuer_name: str
    transaction_code: str
    shares: float
    price_per_share: Optional[float]
    shares_owned_after: float
    acquired_disposed: str

class NarrativeGenerator:
    """Generates natural language summaries for insider transactions."""
    
    @staticmethod
    def generate(tx: InsiderTransaction, footnotes: List[str] = None) -> str:
        footnotes = footnotes or []
        
        # Base action description
        action = "transacted"
        is_sale = False
        is_buy = False
        is_gift = False
        is_grant = False
        
        if tx.transaction_code == 'P':
            action = "bought"
            is_buy = True
        elif tx.transaction_code == 'S':
            action = "sold"
            is_sale = True
        elif tx.transaction_code == 'G':
            action = "gifted"
            is_gift = True
        elif tx.transaction_code == 'A':
            action = "was awarded"
            is_grant = True
        elif tx.transaction_code == 'M':
            action = "exercised options for"
            
        # Ambiguous cases handled by price
        if not is_gift and not is_grant and (tx.price_per_share is None or tx.price_per_share == 0):
            if tx.acquired_disposed == 'A':
                action = "received (grant or award)"
                is_grant = True
            elif tx.acquired_disposed == 'D':
                action = "disposed of (gift or transfer)"
                is_gift = True
                
        # Construct shares part
        # "1,200 shares"
        shares_str = f"{tx.shares:,.0f} shares"
        
        # Construct price part
        price_str = ""
        if is_gift:
            price_str = " (Reported as $0/gift)"
        elif is_grant:
            price_str = " (Grant/Award)"
        elif tx.price_per_share is not None and tx.price_per_share > 0:
            price_str = f" at an average price of ${tx.price_per_share:,.2f}"
            
        # Construct holding part
        holding_str = f" which brings their total ownership to {tx.shares_owned_after:,.0f} shares."
        
        # Sentence construction
        sentence = f"{tx.insider_name}, in position of {tx.insider_title} at {tx.issuer_name} just {action} {shares_str}{price_str}{holding_str}"
        
        # Add footnote context if present
        if footnotes:
            # Combine footnotes into a single context string
            # "Footnote 1 indicates: TEXT. Footnote 2 indicates: TEXT."
            context = " ".join([f"Footnote indicates: {fn}" for fn in footnotes])
            # Truncate if too long (optional, but good for display)
            if len(context) > 200:
                context = context[:197] + "..."
            sentence += f" [{context}]"
            
        return sentence
