// Auto-hide admin messages after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    // Find all admin messages
    var messages = document.querySelectorAll('.messagelist li');
    
    messages.forEach(function(message) {
        // Set timeout to remove/hide after 5 seconds
        setTimeout(function() {
            message.style.transition = 'opacity 0.5s ease';
            message.style.opacity = '0';
            // Remove after animation completes
            setTimeout(function() {
                message.remove();
                // If no messages left, remove the entire list
                var remainingMessages = document.querySelectorAll('.messagelist li');
                if (remainingMessages.length === 0) {
                    var messageList = document.querySelector('.messagelist');
                    if (messageList) {
                        messageList.remove();
                    }
                }
            }, 500);
        }, 5000); // 5000ms = 5 seconds
    });
});