
import main
import socket

def test_check_ip():
    print("Testing check_ip definition...")
    if hasattr(main, 'check_ip'):
        print("✓ check_ip is defined in main.py")
    else:
        print("✗ check_ip is NOT defined in main.py")
        return False
    
    print("Testing check_ip execution (expecting False for random IP)...")
    try:
        result = main.check_ip("1.2.3.4")
        print(f"✓ check_ip executed successfully, result: {result}")
    except Exception as e:
        print(f"✗ check_ip execution failed: {e}")
        return False
        
    return True

if __name__ == "__main__":
    if test_check_ip():
        print("\nVerification SUCCESSFUL")
    else:
        print("\nVerification FAILED")
        exit(1)
