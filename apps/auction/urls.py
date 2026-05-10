from django.urls import path
from django.urls import path
from .views import AuctionNotifyMeView, BiddingHistoryView, CheckoutSummaryView, LiveAuctionsView, UpcomingAuctionsView, JoinAuctionView, AuctionDetailView, UserCategoryListAPIView, WinnerCheckView, SaveAddressView, UserAuctionListAPIView, UserBidHistoryListAPIView, UserConcludedAuctionsListView


app_name = "auction"

urlpatterns = [
    path('live/', LiveAuctionsView.as_view(), name='live_auctions'),
    path('upcoming/', UpcomingAuctionsView.as_view(), name='upcoming_auctions'),
    path('join/', JoinAuctionView.as_view(), name='join_auction'),
    path('detail/', AuctionDetailView.as_view(), name='auction_detail'),
    path('winner-check/', WinnerCheckView.as_view(), name='winner-check'),
    path('save-address/', SaveAddressView.as_view(), name='save-address'),
    path('checkout-summary/', CheckoutSummaryView.as_view(), name='checkout-summary'),
    path('bidding-history/', BiddingHistoryView.as_view(), name='bidding-history'),
    path('categories/', UserCategoryListAPIView.as_view()),
    path('auctions/', UserAuctionListAPIView.as_view()),
    path('notify-me/', AuctionNotifyMeView.as_view(), name='auction-notify-me'),
    path('user-history/', UserBidHistoryListAPIView.as_view(), name='user-history'),
    path('concluded-history/', UserConcludedAuctionsListView.as_view(), name='concluded-history'),
]

