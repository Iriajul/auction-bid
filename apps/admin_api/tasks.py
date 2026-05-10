# apps/admin_api/tasks.py
from celery import shared_task
from django.utils import timezone
from django.db import transaction
from .models import Auction, AuctionStatus
from apps.auction.models import Bid, AuctionWin
from django.db import models
from django.db.models import F, Count
from apps.users.models import UserAddress
from apps.packages.models import UserWallet
import logging
import asyncio

# ---------------- IMPORT FOR ASYNC CELERY ----------------
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)

# -------------------------------
# Task: Publish scheduled auctions
# -------------------------------
@shared_task
def publish_scheduled_auctions():
    """
    Periodic task: Changes SCHEDULE auctions to PUBLISH when time arrives.
    Also sets end_time and sends "Notify Me" push notifications to subscribers.
    """
    now = timezone.now()
    
    due_auctions = Auction.objects.filter(
        status=AuctionStatus.SCHEDULE,
        scheduled_time__lte=now
    )
    
    updated_count = 0
    
    for auction in due_auctions:
        try:
            with transaction.atomic():
                auction.status = AuctionStatus.PUBLISH
                auction.scheduled_time = None
                auction.end_time = now + auction.auction_duration
                auction.save(update_fields=['status', 'scheduled_time', 'end_time'])
                
                updated_count += 1
                
                # ────────────────────────────────────────────────
                # NEW: Send "Auction is Live" push to "Notify Me" subscribers
                # ────────────────────────────────────────────────
                from fcm_django.models import FCMDevice
                from apps.auction.models import AuctionNotificationSubscription
                
                # Get all users who clicked "Notify Me" for this auction
                subscriptions = AuctionNotificationSubscription.objects.filter(
                    auction=auction
                ).select_related('user')
                
                if subscriptions.exists():
                    for sub in subscriptions:
                        # Get all active devices for this user
                        devices = FCMDevice.objects.filter(user=sub.user, active=True)
                        
                        if devices.exists():
                            devices.send_message(
                                title="Auction Started!",
                                body=f"{auction.product_name} is now live!",
                                data={
                                    "auction_id": str(auction.id),
                                    "type": "auction_start",
                                    "product_name": auction.product_name
                                }
                            )
                            logger.info(f"Sent live notification to user {sub.user.email} for auction {auction.id}")
                            
                            # Mark as notified (so we don't spam again)
                            sub.notified = True
                            sub.save(update_fields=['notified'])
                
                    logger.info(f"Sent notifications to {subscriptions.count()} subscribers for auction {auction.id}")
                
            # ────────────────────────────────────────────────
            # 🔥 NEW: Auto-start countdown broadcaster for this auction
            # ────────────────────────────────────────────────
            try:
                from apps.auction.socket import auto_start_auction_countdown
                async_to_sync(auto_start_auction_countdown)(auction.id)
                logger.info(f"Auto-started countdown for auction {auction.id}")
            except Exception as e:
                logger.error(f"Error auto-starting countdown for auction {auction.id}: {e}")
                
        except Exception as e:
            logger.error(f"Error publishing auction {auction.id}: {e}", exc_info=True)
    
    if updated_count > 0:
        logger.info(f"Published {updated_count} scheduled auctions at {now}")
    
    return updated_count


# -------------------------------
# Task: End expired auctions + create win record + refund losers
# -------------------------------
@shared_task
def end_expired_auctions():
    """
    Ends auctions whose end_time has passed.
    - Sets status to ENDED
    - Creates AuctionWin record if there is a winner
    - Refunds losing bidders (1 coin per bid)
    - Emits socket events  
    """
    now = timezone.now()

    expired_auctions = Auction.objects.filter(
        status=AuctionStatus.PUBLISH,
        end_time__isnull=False,
        end_time__lte=now
    )

    ended_count = 0

    for auction in expired_auctions:
        winner = None
        winner_name = None
        
        try:
            with transaction.atomic():
                # Mark auction as ended
                auction.status = AuctionStatus.ENDED
                auction.save(update_fields=['status'])

                # Find winner (highest bid)
                highest_bid = Bid.objects.filter(auction=auction).order_by('-bid_number').first()
                winner = highest_bid.user if highest_bid else None

                # Create AuctionWin record if winner exists
                if winner:
                    AuctionWin.objects.create(
                        auction=auction,
                        winner=winner,
                        final_bid_amount=auction.current_bid,
                        claim_window_end=now + auction.winning_claim_window
                    )
                    logger.info(f"Created AuctionWin record for winner {winner.email} on auction {auction.id}")

                # Refund bidders (properly aggregate all bids)
                # 1. Get total coins per user for this auction
                bidders_query = Bid.objects.filter(auction=auction)
                if winner:
                    bidders_query = bidders_query.exclude(user=winner)
                
                # Aggregate total coins to refund per user
                from django.db.models import Sum
                refund_stats = bidders_query.values('user').annotate(total_refund=Sum('coins_deducted'))
                
                from apps.packages.models import CoinTransaction
                for entry in refund_stats:
                    user_id = entry['user']
                    refund_amount = entry['total_refund']
                    
                    if refund_amount > 0:
                        # Update Wallet
                        UserWallet.objects.filter(user_id=user_id).update(
                            coins=F('coins') + refund_amount
                        )
                        
                        # Create Transaction Log
                        CoinTransaction.objects.create(
                            user_id=user_id,
                            transaction_type='refund',
                            amount=refund_amount,
                            reference_id=auction.id,
                            reference_type='auction_refund',
                            description=f"Refund for bids in Auction #{auction.id} ({auction.product_name})"
                        )
                        logger.info(f"Refunded {refund_amount} coins to user {user_id} for auction {auction.id}")


            # ---------------- SOCKET NOTIFICATIONS ----------------
            # 🔥 FIX: Only broadcast socket events, DON'T call end_auction_and_refund
            # (we already ended auction & refunded above - calling it would cause double refund!)
            try:
                from apps.auction.socket import sio
                
                winner_name = winner.get_full_name() or winner.email if winner else None
                
                # Just broadcast to connected users
                async_to_sync(sio.emit)(
                    'auction_ended',
                    {
                        'auction_id': auction.id,
                        'winner_id': winner.id if winner else None,
                        'winner_name': winner_name,
                        'final_bid': float(auction.current_bid)
                    },
                    room=f"auction_{auction.id}"
                )
                logger.info(f"Broadcasted auction_ended event for auction {auction.id}")
            except Exception as e:
                logger.error(f"Error broadcasting auction ended events for auction {auction.id}: {e}")

            ended_count += 1
            logger.info(f"Auction {auction.id} processed as ended.")

        except Exception as e:
            logger.error(f"Error processing auction {auction.id} in end_expired_auctions: {e}", exc_info=True)

    if ended_count > 0:
        logger.info(f"Auto-ended {ended_count} auctions at {now}")

    return ended_count