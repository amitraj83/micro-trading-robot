#!/usr/bin/env python3
"""
Mock Trading212 portfolio response generator.
Outputs a JSON array of positions and a summary-like cash block matching Trading212 API shape.
"""
import json

MOCK_PORTFOLIO = {
    "cash": {
        "availableToTrade": 5000.0,
        "inPies": 0.0,
        "reservedForOrders": 0.0,
        "currency": "EUR",
    },
    "positions": [
        {
            "instrument": {
                "ticker": "GOOGL_US_EQ",
                "name": "Alphabet (Class A)",
                "isin": "US02079K3059",
                "currency": "USD",
            },
            "createdAt": "2025-12-26T21:19:00.000+02:00",
            "quantity": 1.94970786,
            "quantityAvailableForTrading": 1.94970786,
            "quantityInPies": 0,
            "currentPrice": 316.54,
            "averagePricePaid": 313.55979659,
            "walletImpact": {
                "currency": "EUR",
                "totalCost": 519.22,
                "currentValue": 526.44,
                "unrealizedProfitLoss": 7.22,
                "fxImpact": 2.26,
            },
        },
        {
            "instrument": {
                "ticker": "MSFT_US_EQ",
                "name": "Microsoft",
                "isin": "US5949181045",
                "currency": "USD",
            },
            "createdAt": "2025-12-26T21:17:40.000+02:00",
            "quantity": 1.92862036,
            "quantityAvailableForTrading": 1.92862036,
            "quantityInPies": 0,
            "currentPrice": 485.55,
            "averagePricePaid": 487.60244344,
            "walletImpact": {
                "currency": "EUR",
                "totalCost": 798.8,
                "currentValue": 798.79,
                "unrealizedProfitLoss": -0.01,
                "fxImpact": 3.37,
            },
        },
        {
            "instrument": {
                "ticker": "AVGO_US_EQ",
                "name": "Broadcom",
                "isin": "US11135F1012",
                "currency": "USD",
            },
            "createdAt": "2025-12-26T21:16:45.000+02:00",
            "quantity": 1.99984282,
            "quantityAvailableForTrading": 1.99984282,
            "quantityInPies": 0,
            "currentPrice": 351.64,
            "averagePricePaid": 352.6377138,
            "walletImpact": {
                "currency": "EUR",
                "totalCost": 599.1,
                "currentValue": 599.86,
                "unrealizedProfitLoss": 0.76,
                "fxImpact": 2.46,
            },
        },
    ],
}

if __name__ == "__main__":
    print(json.dumps(MOCK_PORTFOLIO, indent=2))
