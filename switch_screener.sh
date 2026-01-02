#!/bin/bash
# Quick screener switcher - One-liner commands to test different screener types

# Save this script and run: bash switch_screener.sh [screener_type]

SCREENER_TYPE=${1:-day_gainers}
VALID_TYPES=("day_gainers" "most_active" "most_trending" "day_losers")

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Validate input
if [[ ! " ${VALID_TYPES[@]} " =~ " ${SCREENER_TYPE} " ]]; then
    echo -e "${RED}❌ Invalid screener type: $SCREENER_TYPE${NC}"
    echo -e "${YELLOW}Valid options: ${VALID_TYPES[*]}${NC}"
    exit 1
fi

echo -e "${BLUE}🔄 Switching to screener: ${SCREENER_TYPE}${NC}"

# Update .env
sed -i '' "s/YAHOO_SCREENER_TYPE=.*/YAHOO_SCREENER_TYPE=$SCREENER_TYPE/" .env

if grep -q "YAHOO_SCREENER_TYPE=$SCREENER_TYPE" .env; then
    echo -e "${GREEN}✅ Updated .env${NC}"
else
    echo -e "${RED}❌ Failed to update .env${NC}"
    exit 1
fi

# Show new config
echo ""
echo -e "${YELLOW}📋 Current Configuration:${NC}"
grep "YAHOO_SCREENER_TYPE" .env
grep "SYMBOLS=" .env

# Ask to restart
echo ""
echo -e "${YELLOW}Ready to restart bot? (y/n)${NC}"
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}🚀 Restarting bot...${NC}"
    bash restart.sh
else
    echo -e "${YELLOW}⏭  Skipped restart. Run 'bash restart.sh' when ready${NC}"
fi
