// File    : main.go
// Author  : your-email@example.com
// Date    : 2024/9/7
// Description : The entry point of the program.

package main

import (
	"os"
	"payment_config_checker/analysis_sku"
)

// TODO:
// 1. 商品name字段检查是否有非法字符%d
// 2. 优惠券折扣和挽回折扣比例是否正确
// 3. 价格三方id是否存在空格

// mac商店包的买赠是以天为单位的
// mac商店包的三方价格可以提取出来做主商品周期判断
// 程序卡住的问题

func main() {
	// parser := argparse.ArgumentParser(description='Process SKU Excel file.')
	//
	// # 添加命令行参数
	// parser.add_argument('excel_file_path', type=str, help='Path to the Excel file')
	// parser.add_argument('platform', type=str, help='Platform type (e.g., pc, mobile)')
	// parser.add_argument('env', type=str, help='Environment (e.g., online, offline)')
	// parser.add_argument('country', type=str, help='Country code (e.g., US)')

	// 解析参数
	// args = parser.parse_args()
	// excelFilePath := "E://Chrome-Downloads//优惠券SKU验证.xlsx"
	excelFilePath := "E://Chrome-Downloads//2025开学季PC端SKU验证 (5).xlsx"
	platform := "android"
	env := "online"
	country := "us"

	isUWP := false

	cookie := os.Getenv("PAYMENT_ADMIN_COOKIE")

	sheetIndex := 7

	restart := false
	restartIndex := 0
	restartShopWindowID := 0

	// analysis_sku_xls_file(excel_file_path, env, country, platform, is_uwp)
	errorMsgList := analysis_sku.AnalysisSkuXlsFileNew(excelFilePath, env, country, platform, isUWP, sheetIndex, cookie, restart, restartIndex, restartShopWindowID)

	analysis_sku.SendCheckErrorMsgBot(errorMsgList, excelFilePath, sheetIndex)

	// excelFilePath = input("请输入 Excel 文件路径: ")
	// platform = input("请输入平台类型 (例如: pc, mobile): ")
	// env = input("请输入环境 (例如: online, offline): ")
	// country = input("请输入国家代码 (例如: US): ")
	// analysis_sku_xls_file(excel_file_path, env, country, platform)
	//
	// while True:
	//     command = input("程序已完成。输入 'exit' 关闭程序: ").strip().lower()
	//     if command == 'exit':
	//         print("程序关闭。")
	//         break
}
