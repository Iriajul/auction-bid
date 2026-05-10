"""
Production-Grade Auction Socket Handler with Comprehensive Monitoring

Key Improvements:
1. Proper bid processor tracking
2. Auction end timer (works even with no bids)
3. Redis caching for auction data
4. Bid queue with batch processing
5. Rate limiting per user
6. Optimized database queries
7. Memory leak prevention
8. Detailed logging and monitoring
9. Real-time global countdown broadcaster
10. Scheduled auction countdown broadcaster (global + per-auction)
"""

import socketio
import redis.asyncio as redis
from django.db import models, transaction
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import UntypedToken
from channels.db import database_sync_to_async
from apps.auction.models import AuctionParticipant, Bid
from apps.admin_api.models import Auction, AuctionStatus
from apps.packages.models import UserWallet
from django.utils import timezone
from datetime import timedelta
from collections import defaultdict
import asyncio
import logging
import json
import time

try:
    from colorama import Fore, Back, Style, init
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    class Fore:
        GREEN = RED = YELLOW = CYAN = BLUE = MAGENTA = WHITE = ""
    class Back:
        GREEN = BLUE = ""
    class Style:
        RESET_ALL = ""

logger = logging.getLogger(__name__)
User = get_user_model()

# ---------------- CONFIGURATION ----------------
MAX_BIDS_PER_SECOND_PER_USER = 2
BID_BATCH_INTERVAL = 0.1
MAX_PARTICIPANTS_PER_ROOM = 10000
CACHE_TTL = 60

# ---------------- GLOBAL STATE ----------------
connected_users = {}
user_sockets = {}
active_auction_timers = {}
user_bid_timestamps = defaultdict(list)
bid_queues = defaultdict(asyncio.Queue)
active_processors = set()          # live auction_ids with running processors
active_scheduled_broadcasters = set()  # scheduled auction_ids with per-auction broadcaster

# Single flags to prevent duplicate global broadcasters
_global_broadcaster_running = False
_scheduled_broadcaster_running = False

# Statistics tracking
auction_stats = defaultdict(lambda: {
    'total_bids': 0,
    'unique_bidders': set(),
    'last_10_bids': [],
    'started_at': None,
    'extensions': 0
})

# ---------------- REDIS CONNECTION ----------------
redis_client = None

async def get_redis():
    global redis_client
    if redis_client is None:
        try:
            redis_client = await redis.from_url(
                'redis://localhost:6379',
                encoding='utf-8',
                decode_responses=True
            )
            print(f"{Fore.GREEN}✅ Redis connected successfully{Style.RESET_ALL}")
            logger.info("✅ Redis connected")
        except Exception as e:
            print(f"{Fore.RED}❌ Redis connection failed: {e}{Style.RESET_ALL}")
            logger.error(f"❌ Redis connection failed: {e}")
            redis_client = None
    return redis_client

# ---------------- SOCKET.IO SERVER ----------------
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1000000
)

# ---------------- MONITORING & LOGGING ----------------
def print_auction_status(auction_id, auction_data, event_type="UPDATE"):
    """Print detailed auction status to terminal"""
    if not COLORAMA_AVAILABLE:
        return

    now = timezone.now()
    end_time_str = auction_data.get('end_time', 'N/A')

    if end_time_str and end_time_str != 'N/A':
        try:
            from dateutil import parser
            end_time = parser.isoparse(end_time_str)
            remaining = (end_time - now).total_seconds()
            if remaining > 0:
                mins, secs = divmod(int(remaining), 60)
                time_left = f"{mins}m {secs}s"
                time_color = Fore.GREEN if remaining > 60 else Fore.YELLOW if remaining > 10 else Fore.RED
            else:
                time_left = "ENDED"
                time_color = Fore.RED
        except:
            time_left = "Unknown"
            time_color = Fore.WHITE
    else:
        time_left = "N/A"
        time_color = Fore.WHITE

    stats = auction_stats[auction_id]

    print(f"\n{Back.BLUE}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}🎯 AUCTION #{auction_id} - {event_type}{Style.RESET_ALL}")
    print(f"{Back.BLUE}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}⏰ Time Left:{Style.RESET_ALL} {time_color}{time_left}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}💰 Current Bid:{Style.RESET_ALL} {Fore.GREEN}${auction_data.get('current_bid', 0)}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}👥 Total Bids:{Style.RESET_ALL} {Fore.CYAN}{stats['total_bids']}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}👤 Unique Bidders:{Style.RESET_ALL} {Fore.MAGENTA}{len(stats['unique_bidders'])}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}🔄 Extensions:{Style.RESET_ALL} {Fore.BLUE}{stats['extensions']}{Style.RESET_ALL}")

    if stats['last_10_bids']:
        print(f"\n{Fore.CYAN}📊 Recent Bids:{Style.RESET_ALL}")
        for i, bid_info in enumerate(stats['last_10_bids'][-5:], 1):
            print(f"  {i}. {Fore.GREEN}{bid_info['user']}{Style.RESET_ALL} - "
                  f"Bid #{bid_info['bid_num']} at {bid_info['time']}")

    print(f"{Back.BLUE}{'='*80}{Style.RESET_ALL}\n")


def print_winner_announcement(auction_id, winner_name, winner_id, final_bid):
    """Print winner announcement with celebration"""
    if not COLORAMA_AVAILABLE:
        logger.info(f"Auction {auction_id} ended. Winner: {winner_name} (${final_bid})")
        return

    print(f"\n{Back.GREEN}{' '*80}{Style.RESET_ALL}")
    print(f"{Back.GREEN}{Fore.BLACK}🎉 AUCTION #{auction_id} ENDED! 🎉{' '*50}{Style.RESET_ALL}")
    print(f"{Back.GREEN}{' '*80}{Style.RESET_ALL}")

    if winner_name:
        print(f"{Fore.YELLOW}🏆 WINNER:{Style.RESET_ALL} {Fore.GREEN}{winner_name}{Style.RESET_ALL} (ID: {winner_id})")
        print(f"{Fore.YELLOW}💰 Winning Bid:{Style.RESET_ALL} {Fore.GREEN}${final_bid}{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}No winner - No bids placed{Style.RESET_ALL}")

    stats = auction_stats[auction_id]
    print(f"{Fore.YELLOW}📊 Total Bids:{Style.RESET_ALL} {stats['total_bids']}")
    print(f"{Fore.YELLOW}👥 Total Bidders:{Style.RESET_ALL} {len(stats['unique_bidders'])}")
    print(f"{Fore.YELLOW}🔄 Extensions:{Style.RESET_ALL} {stats['extensions']}")

    if stats['started_at']:
        duration = (timezone.now() - stats['started_at']).total_seconds()
        mins, secs = divmod(int(duration), 60)
        print(f"{Fore.YELLOW}⏱️  Duration:{Style.RESET_ALL} {mins}m {secs}s")

    print(f"{Back.GREEN}{' '*80}{Style.RESET_ALL}\n")


# ---------------- CACHING LAYER ----------------
async def cache_get(key):
    try:
        r = await get_redis()
        if r:
            data = await r.get(key)
            return json.loads(data) if data else None
    except Exception as e:
        logger.warning(f"Cache get error: {e}")
    return None


async def cache_set(key, value, ttl=CACHE_TTL):
    try:
        r = await get_redis()
        if r:
            await r.setex(key, ttl, json.dumps(value))
    except Exception as e:
        logger.warning(f"Cache set error: {e}")


async def cache_delete(key):
    try:
        r = await get_redis()
        if r:
            await r.delete(key)
    except Exception as e:
        logger.warning(f"Cache delete error: {e}")


# ---------------- RATE LIMITING ----------------
async def check_rate_limit(user_id, max_per_second=MAX_BIDS_PER_SECOND_PER_USER):
    now = time.time()
    timestamps = user_bid_timestamps[user_id]
    timestamps[:] = [t for t in timestamps if now - t < 1.0]
    if len(timestamps) >= max_per_second:
        return False
    timestamps.append(now)
    return True


# ---------------- OPTIMIZED DB HELPERS ----------------
@database_sync_to_async
def get_user_by_id(user_id):
    return User.objects.select_related().get(id=user_id)


@database_sync_to_async
def get_auction_data(auction_id):
    auction = Auction.objects.select_related().get(id=auction_id)
    return {
        'id': auction.id,
        'status': auction.status,
        'end_time': auction.end_time.isoformat() if auction.end_time else None,
        'created_at': auction.created_at.isoformat(),
        'auction_duration_seconds': auction.auction_duration.total_seconds(),
        'current_bid': float(auction.current_bid),
        'market_price': float(auction.market_price),
        'entry_fee_coins': auction.entry_fee_coins,
        'product_name': auction.product_name,
    }


async def get_auction_cached(auction_id):
    cache_key = f"auction:{auction_id}"
    cached = await cache_get(cache_key)
    if cached:
        return cached
    data = await get_auction_data(auction_id)
    await cache_set(cache_key, data, ttl=10)
    return data


@database_sync_to_async
def deduct_coins_bulk(user_ids, amount=1):
    with transaction.atomic():
        wallets = UserWallet.objects.select_for_update().filter(
            user_id__in=user_ids,
            coins__gte=amount
        )
        wallets.update(coins=models.F('coins') - amount)
        return set(wallets.values_list('user_id', flat=True))


@database_sync_to_async
def refund_coin(user_id, amount=1):
    """Refund coins when bid is rejected"""
    with transaction.atomic():
        wallet = UserWallet.objects.select_for_update().get(user_id=user_id)
        wallet.coins += amount
        wallet.save(update_fields=['coins'])
    return True


@database_sync_to_async
def add_participant_to_auction(auction_id, user_id):
    from apps.auction.models import AuctionParticipant
    participant, created = AuctionParticipant.objects.get_or_create(
        auction_id=auction_id,
        user_id=user_id,
        defaults={'entry_fee_paid': True}
    )
    return created


@database_sync_to_async
def check_if_user_joined(auction_id, user_id):
    from apps.auction.models import AuctionParticipant
    return AuctionParticipant.objects.filter(
        auction_id=auction_id,
        user_id=user_id
    ).exists()

@database_sync_to_async
def get_auction_participants_data(auction_id):
    """Get real-time participant/bid data for a live auction"""
    participants = AuctionParticipant.objects.filter(
        auction_id=auction_id
    ).select_related('user').order_by('-id')

    result = []
    for participant in participants:
        user = participant.user

        last_bid = Bid.objects.filter(
            auction_id=auction_id,
            user=user
        ).order_by('-bid_number').first()

        total_user_bids = Bid.objects.filter(
            auction_id=auction_id,
            user=user
        ).count()

        result.append({
            'user_id': user.id,
            'user_name': user.get_full_name() or user.email,
            'user_email': user.email,
            'total_bids': total_user_bids,
            'last_bid_number': last_bid.bid_number if last_bid else None,
            'last_bid_time': last_bid.bid_at.isoformat() if last_bid else None,
        })

    return result

@database_sync_to_async
def check_and_deduct_entry_fee(user_id, entry_fee):
    with transaction.atomic():
        try:
            wallet = UserWallet.objects.select_for_update().get(user_id=user_id)
            if wallet.coins < entry_fee:
                return False
            wallet.coins -= entry_fee
            wallet.save(update_fields=['coins'])
            return True
        except UserWallet.DoesNotExist:
            return False


# ---------------- SCHEDULED AUCTION DB HELPERS ----------------
@database_sync_to_async
def get_all_scheduled_auctions():
    """Get ALL scheduled auctions with time-until-live countdown"""
    now = timezone.now()
    auctions = Auction.objects.filter(
        status=AuctionStatus.SCHEDULE,
        scheduled_time__isnull=False,
        scheduled_time__gt=now
    ).values('id', 'product_name', 'scheduled_time', 'market_price', 'entry_fee_coins')

    results = []
    for auction in auctions:
        scheduled_time = auction['scheduled_time']
        seconds_until_live = (scheduled_time - now).total_seconds()
        results.append({
            'auction_id': auction['id'],
            'product_name': auction['product_name'],
            'market_price': float(auction['market_price']),
            'entry_fee_coins': auction['entry_fee_coins'],
            'scheduled_time': scheduled_time.isoformat(),
            'seconds_until_live': int(max(seconds_until_live, 0))
        })
    return results


@database_sync_to_async
def get_scheduled_auction_data(auction_id):
    """Get ONE specific scheduled auction with time-until-live"""
    now = timezone.now()
    try:
        auction = Auction.objects.get(
            id=auction_id,
            status=AuctionStatus.SCHEDULE,
            scheduled_time__isnull=False
        )
        seconds_until_live = (auction.scheduled_time - now).total_seconds()
        return {
            'auction_id': auction.id,
            'product_name': auction.product_name,
            'market_price': float(auction.market_price),
            'entry_fee_coins': auction.entry_fee_coins,
            'scheduled_time': auction.scheduled_time.isoformat(),
            'seconds_until_live': int(max(seconds_until_live, 0))
        }
    except Auction.DoesNotExist:
        return None


# ---------------- BATCH BID PROCESSING ----------------
@database_sync_to_async
def process_bids_batch(auction_id, bid_data_list):
    """Process multiple bids in a single transaction"""
    results = []
    extended = False

    with transaction.atomic():
        auction = Auction.objects.select_for_update().get(id=auction_id)

        if auction.status != AuctionStatus.PUBLISH:
            return [(None, False, "Auction not live", extended)] * len(bid_data_list)

        now = timezone.now()
        if auction.end_time and now >= auction.end_time:
            return [(None, False, "Auction ended", extended)] * len(bid_data_list)

        current_bid_num = auction.current_bid
        last_bidder_id = None

        last_bid = Bid.objects.filter(auction=auction).only('user_id').order_by('-id').first()
        if last_bid:
            last_bidder_id = last_bid.user_id

        for user_id, user_obj in bid_data_list:
            if last_bidder_id == user_id:
                results.append((None, False, "Cannot bid twice in a row", extended))
                continue
            try:
                current_bid_num += 1
                bid = Bid.objects.create(
                    auction=auction,
                    user_id=user_id,
                    bid_number=current_bid_num,
                    coins_deducted=1
                )
                last_bidder_id = user_id
                results.append((bid, True, None, extended))
            except Exception as e:
                results.append((None, False, str(e), extended))

        auction.current_bid = current_bid_num
        auction.last_bid_time = now

        # Anti-sniping extension
        if auction.end_time:
            remaining = (auction.end_time - now).total_seconds()
            if remaining <= 5:
                auction.end_time = now + timedelta(seconds=5)
                extended = True
                print(f"{Fore.YELLOW}⏰ Auction #{auction_id} timer reset to 5s! "
                    f"(was {remaining:.1f}s remaining){Style.RESET_ALL}")
        else:
            auction.end_time = auction.created_at + auction.auction_duration

        auction.save(update_fields=['current_bid', 'last_bid_time', 'end_time'])

    return results


async def bid_processor_worker(auction_id):
    """Background worker that processes bids in batches"""
    active_processors.add(auction_id)
    print(f"{Fore.CYAN}🚀 Started bid processor for Auction #{auction_id}{Style.RESET_ALL}")
    logger.info(f"Started bid processor for auction {auction_id}")

    try:
        queue = bid_queues[auction_id]

        while True:
            try:
                batch = []
                deadline = asyncio.get_event_loop().time() + BID_BATCH_INTERVAL

                while len(batch) < 50:
                    timeout = deadline - asyncio.get_event_loop().time()
                    if timeout <= 0:
                        break
                    try:
                        bid_data = await asyncio.wait_for(queue.get(), timeout=timeout)
                        batch.append(bid_data)
                    except asyncio.TimeoutError:
                        break

                if not batch:
                    continue

                batch_start = time.time()
                user_data = [(uid, uobj) for uid, uobj, sid in batch]
                results = await process_bids_batch(auction_id, user_data)
                processing_time = (time.time() - batch_start) * 1000

                await cache_delete(f"auction:{auction_id}")
                auction_data = await get_auction_cached(auction_id)

                stats = auction_stats[auction_id]
                if stats['started_at'] is None:
                    stats['started_at'] = timezone.now()

                extended_in_batch = False
                successful_bids = 0

                for (user_id, user_obj, sid), (bid, success, error, extended) in zip(batch, results):
                    if success and bid:
                        successful_bids += 1
                        stats['total_bids'] += 1
                        stats['unique_bidders'].add(user_id)

                        if extended:
                            stats['extensions'] += 1
                            extended_in_batch = True

                        stats['last_10_bids'].append({
                            'user': user_obj.get_full_name() or user_obj.email,
                            'bid_num': bid.bid_number,
                            'time': bid.bid_at.strftime('%H:%M:%S')
                        })
                        if len(stats['last_10_bids']) > 10:
                            stats['last_10_bids'] = stats['last_10_bids'][-10:]

                        saving = auction_data['market_price'] - auction_data['current_bid']
                        payload = {
                            'auction_id': auction_id,
                            'current_bid': float(auction_data['current_bid']),
                            'amount_saving': float(max(saving, 0)),
                            'user_id': user_id,
                            'user_name': user_obj.get_full_name() or user_obj.email,
                            'bid_time': bid.bid_at.isoformat(),
                            'bid_number': bid.bid_number,
                            'timer_extended': extended
                        }
                        await sio.emit('new_bid', payload, room=f"auction_{auction_id}")

                        # Detailed event for admin dashboard
                        await sio.emit('live_bid_users_response', {
                            'auction_id': auction_id,
                            'bid_number': bid.bid_number,
                            'user_id': user_id,
                            'user_name': user_obj.get_full_name() or user_obj.email,
                            'user_email': user_obj.email,
                            'bid_time': bid.bid_at.isoformat(),
                            'current_bid': float(auction_data['current_bid']),
                            'market_price': float(auction_data['market_price']),
                            'amount_saving': float(max(saving, 0)),
                            'timer_extended': extended,
                            'total_bids': stats['total_bids'],
                            'unique_bidders': len(stats['unique_bidders']),
                            'extensions': stats['extensions'],
                        }, room=f"admin_auction_{auction_id}")

                        print(f"{Fore.GREEN}✅ BID #{bid.bid_number}{Style.RESET_ALL} "
                              f"by {Fore.CYAN}{user_obj.get_full_name() or user_obj.email}{Style.RESET_ALL} "
                              f"on Auction #{auction_id} - ${auction_data['current_bid']}")
                    else:
                        await refund_coin(user_id)
                        await sio.emit('error', {'error': error or 'Bid failed'}, to=sid)
                        print(f"{Fore.RED}❌ Bid rejected for {user_obj.get_full_name() or user_obj.email}: {error} (coin refunded){Style.RESET_ALL}")

                if successful_bids > 0:
                    print(f"{Fore.MAGENTA}📦 Processed batch of {successful_bids} bids "
                          f"in {processing_time:.1f}ms for Auction #{auction_id}{Style.RESET_ALL}")
                    if stats['total_bids'] % 10 == 0 or extended_in_batch:
                        print_auction_status(auction_id, auction_data, "BATCH UPDATE")

            except Exception as e:
                logger.error(f"Bid processor error for auction {auction_id}: {e}", exc_info=True)
                print(f"{Fore.RED}❌ Error in bid processor: {e}{Style.RESET_ALL}")
                await asyncio.sleep(1)

    finally:
        active_processors.discard(auction_id)
        print(f"{Fore.RED}🛑 Stopped bid processor for Auction #{auction_id}{Style.RESET_ALL}")
        logger.info(f"Stopped bid processor for auction {auction_id}")


# ---------------- AUCTION END LOGIC ----------------
@database_sync_to_async
def end_auction_and_refund_sync(auction_id):
    """Atomic auction ending with bulk refund"""
    with transaction.atomic():
        auction = Auction.objects.select_for_update().get(id=auction_id)

        if auction.status == AuctionStatus.ENDED:
            return False, None, None, 0

        now = timezone.now()
        if auction.end_time and now < auction.end_time:
            return False, None, None, 0

        auction.status = AuctionStatus.ENDED
        auction.save(update_fields=['status'])

        # Find winner
        highest_bid = Bid.objects.filter(auction=auction).order_by('-bid_number').first()
        winner = highest_bid.user if highest_bid else None
        
        # 🔥 FIX: Create AuctionWin record if there's a winner
        if winner:
            from apps.auction.models import AuctionWin
            
            # Use get_or_create to prevent duplicates
            AuctionWin.objects.get_or_create(
                auction=auction,
                defaults={
                    'winner': winner,
                    'final_bid_amount': auction.current_bid,
                    'claim_window_end': now + auction.winning_claim_window
                }
            )
            logger.info(f"✅ Created AuctionWin record for {winner.email} on auction {auction_id}")

        # Bulk refund
        if winner:
            losing_user_ids = Bid.objects.filter(
                auction=auction
            ).exclude(user=winner).values_list('user_id', flat=True).distinct()
            
            UserWallet.objects.filter(user_id__in=losing_user_ids).update(
                coins=models.F('coins') + 1
            )
            refund_count = len(set(losing_user_ids))
        else:
            all_user_ids = Bid.objects.filter(
                auction=auction
            ).values_list('user_id', flat=True).distinct()
            
            UserWallet.objects.filter(user_id__in=all_user_ids).update(
                coins=models.F('coins') + 1
            )
            refund_count = len(set(all_user_ids))
        
        logger.info(f"✅ Ended auction {auction_id}, refunded {refund_count} users")
        
        winner_name = winner.get_full_name() or winner.email if winner else None
        winner_id = winner.id if winner else None
        final_bid = float(auction.current_bid)
        
        return True, winner_id, winner_name, final_bid


async def end_auction_and_refund(auction_id):
    """End auction and broadcast"""
    success, winner_id, winner_name, final_bid = await end_auction_and_refund_sync(auction_id)
    if not success:
        return False

    await cache_delete(f"auction:{auction_id}")
    print_winner_announcement(auction_id, winner_name, winner_id, final_bid)

    await sio.emit('auction_ended', {
        'auction_id': auction_id,
        'winner_id': winner_id,
        'winner_name': winner_name,
        'final_bid': final_bid
    }, room=f"auction_{auction_id}")

    if auction_id in active_auction_timers:
        active_auction_timers[auction_id].cancel()
        del active_auction_timers[auction_id]

    bid_queues.pop(auction_id, None)
    auction_stats.pop(auction_id, None)
    active_processors.discard(auction_id)
    return True


async def broadcast_countdown(auction_id):
    """
    Broadcast real-time countdown to all users in a specific live auction room.
    Event: 'countdown_update' → room: auction_{auction_id}
    Runs every 1 second until auction ends.
    """
    print(f"{Fore.CYAN}📡 Started countdown broadcaster for Auction #{auction_id}{Style.RESET_ALL}")

    try:
        while auction_id in active_processors:
            try:
                auction_data = await get_auction_cached(auction_id)

                if auction_data['status'] != AuctionStatus.PUBLISH:
                    break

                if auction_data['end_time']:
                    from dateutil import parser
                    end_time = parser.isoparse(auction_data['end_time'])
                    now = timezone.now()
                    remaining_seconds = (end_time - now).total_seconds()

                    if remaining_seconds <= 0:
                        break

                    await sio.emit('countdown_update', {
                        'auction_id': auction_id,
                        'remaining_seconds': int(remaining_seconds),
                        'end_time': auction_data['end_time']
                    }, room=f"auction_{auction_id}")

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Countdown broadcast error for auction {auction_id}: {e}")
                await asyncio.sleep(1)

    finally:
        print(f"{Fore.RED}📡 Stopped countdown broadcaster for Auction #{auction_id}{Style.RESET_ALL}")


async def schedule_auction_end(auction_id, delay_seconds):
    """Schedule auction to end after delay"""
    if auction_id in active_auction_timers:
        active_auction_timers[auction_id].cancel()

    print(f"{Fore.YELLOW}⏰ Scheduled Auction #{auction_id} to end in {delay_seconds:.1f}s{Style.RESET_ALL}")

    async def end_task():
        try:
            await asyncio.sleep(delay_seconds)
            print(f"{Fore.RED}⏰ Timer expired for Auction #{auction_id}, ending now...{Style.RESET_ALL}")
            await end_auction_and_refund(auction_id)
        except asyncio.CancelledError:
            print(f"{Fore.YELLOW}⏰ Timer cancelled for Auction #{auction_id}{Style.RESET_ALL}")
        except Exception as e:
            logger.error(f"Error ending auction {auction_id}: {e}", exc_info=True)

    task = asyncio.create_task(end_task())
    active_auction_timers[auction_id] = task


# ---------------- LIVE AUCTIONS GLOBAL BROADCASTER ----------------
@database_sync_to_async
def get_all_live_auctions():
    """Get all live auctions with countdown data"""
    now = timezone.now()
    auctions = Auction.objects.filter(
        status=AuctionStatus.PUBLISH,
        end_time__isnull=False,
        end_time__gt=now
    ).values('id', 'product_name', 'end_time', 'current_bid', 'market_price', 'entry_fee_coins')

    results = []
    for auction in auctions:
        end_time = auction['end_time']
        remaining_seconds = (end_time - now).total_seconds()
        results.append({
            'auction_id': auction['id'],
            'product_name': auction['product_name'],
            'current_bid': float(auction['current_bid']),
            'market_price': float(auction['market_price']),
            'entry_fee_coins': auction['entry_fee_coins'],
            'end_time': end_time.isoformat(),
            'remaining_seconds': int(max(remaining_seconds, 0))
        })
    return results


async def broadcast_all_countdowns():
    """
    Broadcast countdown for ALL live auctions every 1 second to every connected user.
    Event: 'all_countdowns'
    Only one instance runs at a time via _global_broadcaster_running flag.
    """
    global _global_broadcaster_running

    if _global_broadcaster_running:
        print(f"{Fore.YELLOW}📡 Global broadcaster already running, skipping duplicate start{Style.RESET_ALL}")
        return

    _global_broadcaster_running = True
    cycle_num = 0

    print(f"{Fore.CYAN}📡 Started global live countdown broadcaster{Style.RESET_ALL}")
    logger.info("📡 Global countdown broadcaster started")

    try:
        while True:
            try:
                cycle_num += 1
                auctions = await get_all_live_auctions()

                if not auctions:
                    await asyncio.sleep(1)
                    continue

                # Log every 30 cycles to avoid terminal spam
                if cycle_num % 30 == 1:
                    print(f"{Fore.CYAN}📡 [Cycle {cycle_num}] Broadcasting {len(auctions)} live auction(s):{Style.RESET_ALL}")
                    for a in auctions:
                        mins, secs = divmod(a['remaining_seconds'], 60)
                        print(f"   └─ Auction #{a['auction_id']} | "
                              f"{Fore.YELLOW}{a['product_name']}{Style.RESET_ALL} | "
                              f"⏰ {mins}m {secs}s left | 💰 ${a['current_bid']}")

                await sio.emit('all_countdowns', {
                    'auctions': auctions,
                    'count': len(auctions),
                    'timestamp': timezone.now().isoformat()
                })

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Global countdown broadcast error on cycle {cycle_num}: {e}", exc_info=True)
                print(f"{Fore.RED}❌ Broadcast error on cycle {cycle_num}: {e}{Style.RESET_ALL}")
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        print(f"{Fore.RED}📡 Global countdown broadcaster cancelled{Style.RESET_ALL}")
    finally:
        _global_broadcaster_running = False
        print(f"{Fore.RED}📡 Stopped global countdown broadcaster{Style.RESET_ALL}")
        logger.info("📡 Global countdown broadcaster stopped")


# ---------------- SCHEDULED AUCTIONS GLOBAL BROADCASTER ----------------
async def broadcast_scheduled_countdowns():
    """
    Broadcast countdown for ALL scheduled auctions every 1 second to every connected user.
    Event: 'scheduled_countdowns'
    When Celery publishes an auction, it vanishes from here and appears in all_countdowns.
    Only one instance runs at a time via _scheduled_broadcaster_running flag.
    """
    global _scheduled_broadcaster_running

    if _scheduled_broadcaster_running:
        print(f"{Fore.YELLOW}📅 Scheduled broadcaster already running, skipping duplicate start{Style.RESET_ALL}")
        return

    _scheduled_broadcaster_running = True
    cycle_num = 0

    print(f"{Fore.CYAN}📅 Started global scheduled auctions broadcaster{Style.RESET_ALL}")
    logger.info("📅 Scheduled countdown broadcaster started")

    try:
        while True:
            try:
                cycle_num += 1
                auctions = await get_all_scheduled_auctions()

                if not auctions:
                    await asyncio.sleep(1)
                    continue

                # Log every 30 cycles to avoid terminal spam
                if cycle_num % 30 == 1:
                    print(f"{Fore.CYAN}📅 [Cycle {cycle_num}] {len(auctions)} scheduled auction(s):{Style.RESET_ALL}")
                    for a in auctions:
                        h, remainder = divmod(a['seconds_until_live'], 3600)
                        m, s = divmod(remainder, 60)
                        print(f"   └─ Auction #{a['auction_id']} | "
                              f"{Fore.YELLOW}{a['product_name']}{Style.RESET_ALL} | "
                              f"🕐 Live in {h}h {m}m {s}s")

                await sio.emit('scheduled_countdowns', {
                    'auctions': auctions,
                    'count': len(auctions),
                    'timestamp': timezone.now().isoformat()
                })

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Scheduled countdown error on cycle {cycle_num}: {e}", exc_info=True)
                print(f"{Fore.RED}❌ Scheduled broadcast error on cycle {cycle_num}: {e}{Style.RESET_ALL}")
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        print(f"{Fore.RED}📅 Scheduled countdown broadcaster cancelled{Style.RESET_ALL}")
    finally:
        _scheduled_broadcaster_running = False
        print(f"{Fore.RED}📅 Stopped global scheduled broadcaster{Style.RESET_ALL}")
        logger.info("📅 Scheduled countdown broadcaster stopped")


# ---------------- PER-AUCTION SCHEDULED BROADCASTER ----------------
async def broadcast_single_scheduled_countdown(auction_id):
    """
    Broadcast countdown for ONE specific scheduled auction every 1 second.
    Event: 'scheduled_countdown_update' → room: scheduled_{auction_id}
    Stops automatically when auction goes live (Celery changes status to PUBLISH).
    Emits 'auction_now_live' so frontend can redirect user to join the live auction.
    """
    print(f"{Fore.CYAN}📅 Started per-auction scheduled broadcaster for Auction #{auction_id}{Style.RESET_ALL}")
    logger.info(f"Per-auction scheduled broadcaster started for auction {auction_id}")

    try:
        while True:
            try:
                auction_data = await get_scheduled_auction_data(auction_id)

                # Returns None when auction is no longer SCHEDULE (Celery published it)
                if not auction_data:
                    print(f"{Fore.GREEN}📅 Auction #{auction_id} is now live! Notifying detail page users...{Style.RESET_ALL}")
                    await sio.emit('auction_now_live', {
                        'auction_id': auction_id,
                        'message': 'Auction is now live! Join to start bidding.'
                    }, room=f"scheduled_{auction_id}")
                    break

                if auction_data['seconds_until_live'] <= 0:
                    break

                await sio.emit('scheduled_countdown_update', {
                    'auction_id': auction_id,
                    'product_name': auction_data['product_name'],
                    'market_price': auction_data['market_price'],
                    'entry_fee_coins': auction_data['entry_fee_coins'],
                    'scheduled_time': auction_data['scheduled_time'],
                    'seconds_until_live': auction_data['seconds_until_live']
                }, room=f"scheduled_{auction_id}")

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Per-auction scheduled broadcaster error for auction {auction_id}: {e}")
                await asyncio.sleep(1)

    finally:
        # Clean up so a new broadcaster can start if needed
        active_scheduled_broadcasters.discard(auction_id)
        print(f"{Fore.RED}📅 Stopped per-auction scheduled broadcaster for Auction #{auction_id}{Style.RESET_ALL}")
        logger.info(f"Per-auction scheduled broadcaster stopped for auction {auction_id}")


# ---------------- SOCKET EVENTS ----------------
@sio.event
async def connect(sid, environ, auth):
    token = auth.get('token') if auth else None
    if not token:
        print(f"{Fore.RED}❌ Connection rejected: No token{Style.RESET_ALL}")
        return False

    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = UntypedToken(token)
        user_id = int(payload['user_id'])
        user = await get_user_by_id(user_id)
    except Exception as e:
        logger.warning(f"Auth failed: {e}")
        print(f"{Fore.RED}❌ Auth failed: {e}{Style.RESET_ALL}")
        return False

    connected_users[sid] = user_id
    user_sockets[user_id] = sid
    await sio.save_session(sid, {'user_id': user_id})

    print(f"{Fore.GREEN}✅ Connected:{Style.RESET_ALL} {Fore.CYAN}{user.email}{Style.RESET_ALL} "
          f"(Total: {Fore.YELLOW}{len(connected_users)}{Style.RESET_ALL})")
    logger.info(f"✅ Connected: {user.email} (total: {len(connected_users)})")

    # Auto-start global live auction broadcaster on first connection
    if not _global_broadcaster_running:
        print(f"{Fore.CYAN}📡 Starting global live auction broadcaster{Style.RESET_ALL}")
        asyncio.create_task(broadcast_all_countdowns())

    # Auto-start global scheduled auction broadcaster on first connection
    if not _scheduled_broadcaster_running:
        print(f"{Fore.CYAN}📅 Starting global scheduled auction broadcaster{Style.RESET_ALL}")
        asyncio.create_task(broadcast_scheduled_countdowns())

    return True


@sio.event
async def watch_scheduled_auction(sid, data):
    """
    User opens the detail page of a specific scheduled auction.
    Joins room: scheduled_{auction_id}
    Receives 'scheduled_countdown_update' every second (per-auction, not the global list).
    Receives 'auction_now_live' when Celery publishes the auction — frontend should redirect.

    Frontend:
        socket.emit('watch_scheduled_auction', { auction_id: 210 })
        socket.on('scheduled_countdown_update', (data) => { ... })
        socket.on('auction_now_live', (data) => { redirect to join page })
    """
    user_id = connected_users.get(sid)
    auction_id = data.get('auction_id')

    if not user_id or not auction_id:
        return

    try:
        auction_data = await get_scheduled_auction_data(auction_id)

        if not auction_data:
            await sio.emit('error', {
                'error': 'Auction not found or no longer scheduled'
            }, to=sid)
            return

        # Join this auction's specific scheduled room
        await sio.enter_room(sid, f"scheduled_{auction_id}")

        h, remainder = divmod(auction_data['seconds_until_live'], 3600)
        m, s = divmod(remainder, 60)
        print(f"{Fore.CYAN}📅 User {user_id} watching scheduled Auction #{auction_id} "
              f"(live in {h}h {m}m {s}s){Style.RESET_ALL}")
        logger.info(f"User {user_id} watching scheduled auction {auction_id}")

        # Send immediate snapshot to this user
        await sio.emit('scheduled_countdown_update', {
            'auction_id': auction_id,
            'product_name': auction_data['product_name'],
            'market_price': auction_data['market_price'],
            'entry_fee_coins': auction_data['entry_fee_coins'],
            'scheduled_time': auction_data['scheduled_time'],
            'seconds_until_live': auction_data['seconds_until_live']
        }, to=sid)

        # Start per-auction broadcaster only if not already running for this auction
        if auction_id not in active_scheduled_broadcasters:
            active_scheduled_broadcasters.add(auction_id)
            asyncio.create_task(broadcast_single_scheduled_countdown(auction_id))
            print(f"{Fore.MAGENTA}🆕 Started new per-auction broadcaster for Auction #{auction_id}{Style.RESET_ALL}")
        else:
            print(f"{Fore.BLUE}♻️  Using existing per-auction broadcaster for Auction #{auction_id}{Style.RESET_ALL}")

    except Exception as e:
        logger.error(f"Watch scheduled auction error: {e}", exc_info=True)
        await sio.emit('error', {'error': 'Failed to watch scheduled auction'}, to=sid)


@sio.event
async def monitor_auction(sid, data):
    """
    View-only access to a live auction (for admins/observers).
    No entry fee. No bidding. Receives all live updates.
    """
    user_id = connected_users.get(sid)
    auction_id = data.get('auction_id')

    if not user_id or not auction_id:
        return

    try:
        user = await get_user_by_id(user_id)
        auction_data = await get_auction_cached(auction_id)

        await sio.enter_room(sid, f"auction_{auction_id}")

        print(f"{Fore.YELLOW}👁️  MONITOR MODE:{Style.RESET_ALL} {Fore.CYAN}{user.email}{Style.RESET_ALL} "
              f"is monitoring {Fore.YELLOW}Auction #{auction_id}{Style.RESET_ALL} (view-only)")
        logger.info(f"User {user_id} monitoring auction {auction_id} (view-only)")

        if auction_id not in active_processors and auction_data['status'] == AuctionStatus.PUBLISH:
            print(f"{Fore.MAGENTA}🆕 Starting processors for monitored Auction #{auction_id}{Style.RESET_ALL}")
            active_processors.add(auction_id)

            if auction_id not in bid_queues:
                bid_queues[auction_id] = asyncio.Queue()

            asyncio.create_task(bid_processor_worker(auction_id))
            asyncio.create_task(broadcast_countdown(auction_id))

            if auction_data['end_time']:
                from dateutil import parser
                end_time = parser.isoparse(auction_data['end_time'])
                now = timezone.now()
                remaining = (end_time - now).total_seconds()
                if remaining > 0:
                    await schedule_auction_end(auction_id, remaining)

        await sio.emit('auction_state', {
            'auction_id': auction_id,
            'status': auction_data['status'],
            'current_bid': auction_data['current_bid'],
            'end_time': auction_data['end_time']
        }, to=sid)

    except Exception as e:
        logger.error(f"Monitor error: {e}", exc_info=True)
        await sio.emit('error', {'error': 'Failed to monitor auction'}, to=sid)


@sio.event
async def admin_watch_auction(sid, data):
    """
    Admin joins a separate room to monitor live bid activity.
    Receives 'live_bid_users_response' on every bid.
    Room: admin_auction_{auction_id}
    """
    user_id = connected_users.get(sid)
    auction_id = data.get('auction_id')

    if not user_id or not auction_id:
        return

    try:
        user = await get_user_by_id(user_id)

        # Uncomment to restrict to staff only:
        # if not user.is_staff:
        #     await sio.emit('error', {'error': 'Unauthorized'}, to=sid)
        #     return

        await sio.enter_room(sid, f"admin_auction_{auction_id}")

        print(f"{Fore.YELLOW}🛡️  ADMIN watching Auction #{auction_id}: {user.email}{Style.RESET_ALL}")
        logger.info(f"Admin {user_id} watching auction {auction_id}")

        # Send current snapshot immediately
        auction_data = await get_auction_cached(auction_id)
        stats = auction_stats[auction_id]

        await sio.emit('live_bid_users_response', {
            'auction_id': auction_id,
            'snapshot': True,
            'current_bid': float(auction_data['current_bid']),
            'total_bids': stats['total_bids'],
            'unique_bidders': len(stats['unique_bidders']),
            'extensions': stats['extensions'],
            'recent_bids': stats['last_10_bids'],
        }, to=sid)

    except Exception as e:
        logger.error(f"Admin watch error: {e}", exc_info=True)
        await sio.emit('error', {'error': 'Failed to watch auction'}, to=sid)


@sio.event
async def join_auction(sid, data):
    user_id = connected_users.get(sid)
    auction_id = data.get('auction_id')

    if not user_id or not auction_id:
        return

    try:
        user = await get_user_by_id(user_id)
        auction_data = await get_auction_cached(auction_id)

        if auction_data['status'] != AuctionStatus.PUBLISH:
            await sio.emit('error', {'error': 'Auction not live'}, to=sid)
            return

        already_joined = await check_if_user_joined(auction_id, user_id)

        if not already_joined:
            entry_fee = auction_data['entry_fee_coins']
            has_coins = await check_and_deduct_entry_fee(user_id, entry_fee)

            if not has_coins:
                await sio.emit('error', {
                    'error': f'Not enough coins. Need {entry_fee} coins to join this auction.'
                }, to=sid)
                print(f"{Fore.RED}❌ User {user.email} rejected - not enough coins (need {entry_fee}){Style.RESET_ALL}")
                return

            is_new_participant = await add_participant_to_auction(auction_id, user_id)
            print(f"{Fore.GREEN}✅ Entry fee deducted: {entry_fee} coins from {user.email}{Style.RESET_ALL}")
        else:
            is_new_participant = False

        await sio.enter_room(sid, f"auction_{auction_id}")

        # Notify others in room that a user joined
        await sio.emit('user_joined', {
            'auction_id': auction_id,
            'user_id': user_id,
            'user_name': user.get_full_name() or user.email,
            'is_new_participant': is_new_participant,
            'joined_at': timezone.now().isoformat()
        }, room=f"auction_{auction_id}", skip_sid=sid)

        if auction_id not in active_processors:
            if auction_id not in bid_queues:
                bid_queues[auction_id] = asyncio.Queue()

            asyncio.create_task(bid_processor_worker(auction_id))
            print(f"{Fore.MAGENTA}🆕 Starting NEW bid processor for Auction #{auction_id}{Style.RESET_ALL}")

            asyncio.create_task(broadcast_countdown(auction_id))

            if auction_data['end_time']:
                from dateutil import parser
                end_time = parser.isoparse(auction_data['end_time'])
                now = timezone.now()
                remaining = (end_time - now).total_seconds()

                if remaining > 0:
                    await schedule_auction_end(auction_id, remaining)
                else:
                    print(f"{Fore.RED}⚠️  Auction #{auction_id} already expired, ending now...{Style.RESET_ALL}")
                    asyncio.create_task(end_auction_and_refund(auction_id))
        else:
            print(f"{Fore.BLUE}♻️  Using EXISTING bid processor for Auction #{auction_id}{Style.RESET_ALL}")

        if is_new_participant:
            print(f"{Fore.GREEN}✅ NEW participant:{Style.RESET_ALL} {Fore.CYAN}{user.email}{Style.RESET_ALL} "
                  f"added to Auction #{auction_id} (saved to database)")
        else:
            print(f"{Fore.YELLOW}♻️  RETURNING participant:{Style.RESET_ALL} {Fore.CYAN}{user.email}{Style.RESET_ALL} "
                  f"rejoined Auction #{auction_id}")

        print(f"{Fore.BLUE}👤 User {Fore.CYAN}{user.email}{Style.RESET_ALL} "
              f"joined {Fore.YELLOW}Auction #{auction_id}{Style.RESET_ALL}")
        logger.info(f"User {user_id} joined auction {auction_id}")

    except Exception as e:
        logger.error(f"Join error: {e}", exc_info=True)
        await sio.emit('error', {'error': 'Failed to join'}, to=sid)


@sio.event
async def place_bid(sid, data):
    user_id = connected_users.get(sid)
    auction_id = data.get('auction_id')

    if not user_id or not auction_id:
        return

    if auction_id not in active_processors:
        await sio.emit('error', {
            'error': 'Auction processor not ready. Please rejoin the auction.'
        }, to=sid)
        print(f"{Fore.RED}⚠️  Bid rejected - no processor for Auction #{auction_id}{Style.RESET_ALL}")
        return

    if not await check_rate_limit(user_id):
        await sio.emit('error', {'error': 'Too many bids, slow down'}, to=sid)
        print(f"{Fore.RED}⚠️  Rate limit hit for user {user_id}{Style.RESET_ALL}")
        return

    try:
        user = await get_user_by_id(user_id)

        success_ids = await deduct_coins_bulk([user_id], amount=1)
        if user_id not in success_ids:
            await sio.emit('error', {'error': 'Not enough coins'}, to=sid)
            return

        await bid_queues[auction_id].put((user_id, user, sid))

    except Exception as e:
        logger.error(f"Bid error: {e}", exc_info=True)
        await sio.emit('error', {'error': 'Bid failed'}, to=sid)


# ---------------- AUTO-START COUNTDOWN (Called from Celery) ----------------
async def auto_start_auction_countdown(auction_id):
    """
    Auto-start countdown broadcaster and timer for an auction.
    Called when auction is published by Celery (even if no users join).
    """
    if auction_id in active_processors:
        logger.info(f"Countdown already running for auction {auction_id}")
        return

    try:
        active_processors.add(auction_id)

        if auction_id not in bid_queues:
            bid_queues[auction_id] = asyncio.Queue()

        auction_data = await get_auction_cached(auction_id)

        asyncio.create_task(bid_processor_worker(auction_id))
        asyncio.create_task(broadcast_countdown(auction_id))

        if not _global_broadcaster_running:
            asyncio.create_task(broadcast_all_countdowns())

        if not _scheduled_broadcaster_running:
            asyncio.create_task(broadcast_scheduled_countdowns())

        if auction_data['end_time']:
            from dateutil import parser
            end_time = parser.isoparse(auction_data['end_time'])
            now = timezone.now()
            remaining = (end_time - now).total_seconds()

            if remaining > 0:
                await schedule_auction_end(auction_id, remaining)
            else:
                asyncio.create_task(end_auction_and_refund(auction_id))

        print(f"{Fore.GREEN}🚀 Auto-started countdown for Auction #{auction_id}{Style.RESET_ALL}")
        logger.info(f"Auto-started countdown for auction {auction_id}")

    except Exception as e:
        logger.error(f"Error auto-starting auction {auction_id}: {e}", exc_info=True)
        active_processors.discard(auction_id)


@sio.event
async def live_bid_users(sid, data):
    """
    Return real-time user list for the auction
    Accessible by all authenticated users
    """
    user_id = connected_users.get(sid)
    auction_id = data.get('auction_id')
    
    if not user_id or not auction_id:
        return
        
    try:
        # Check permissions - Removed to allow all users access
        user = await get_user_by_id(user_id)

        participants = await get_auction_participants_data(auction_id)
        await sio.emit('live_bid_users_response', {
            'auction_id': auction_id,
            'participants': participants
        }, to=sid)
        
    except Exception as e:
        logger.error(f"Live bid users error: {e}", exc_info=True)
        await sio.emit('error', {'error': f'Failed to fetch participant list: {str(e)}'}, to=sid)

# ---------------- DISCONNECT ----------------
@sio.event
async def disconnect(sid):
    user_id = connected_users.pop(sid, None)
    if user_id:
        user_sockets.pop(user_id, None)
        asyncio.create_task(cleanup_user_data(user_id))

    print(f"{Fore.RED}❌ Disconnected:{Style.RESET_ALL} user_id={user_id} "
          f"(Total: {Fore.YELLOW}{len(connected_users)}{Style.RESET_ALL})")
    logger.info(f"❌ Disconnected: user_id={user_id} (total: {len(connected_users)})")


async def cleanup_user_data(user_id):
    """Clean up user data after disconnect"""
    await asyncio.sleep(300)
    if user_id not in user_sockets:
        user_bid_timestamps.pop(user_id, None)