# This is just the fixed process_tick method
# Lines 312-318 should be:

                # Update loss counter
                if trade_to_close.pnl < 0:
                    self.consecutive_losses_counter += 1
                else:
                    self.consecutive_losses_counter = 0
            else:
                event["no_trade_reason"] = f"Position open: {self.current_position.direction} @ ${self.current_position.entry_price:.2f}"
